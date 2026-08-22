from email.utils import formataddr, parseaddr

from odoo import api, fields, models, tools


class MailMail(models.Model):
    _inherit = "mail.mail"

    _AFFINITY_MODELS = {
        "sale.order",
        "account.move",
        "stock.picking",
        "payment.transaction",
    }

    @api.model_create_multi
    def create(self, vals_list):
        """Resolve sender pool before creating mail.mail records.

        The selected SMTP server, From and Reply-To are creation-time values.
        This keeps the send/queue path read-only with respect to sender
        selection and avoids a write for every queued mail immediately before
        SMTP delivery.
        """
        today = fields.Date.context_today(self)
        partner_cache = {}
        selected_for_partner = {}
        pending_affinity = {"signup": {}, "order": {}}
        pool_indexes = {"signup": [], "order": []}

        # Resolve the target partner from the values without creating mail.mail.
        for vals in vals_list:
            model = vals.get("model")
            res_id = vals.get("res_id")
            partner = self._partner_from_values(model, res_id, vals.get("recipient_ids"))
            if partner:
                partner_cache[id(vals)] = partner

        # First pass: preserve existing same-day customer affinity.
        for vals in vals_list:
            partner = partner_cache.get(id(vals))
            server_id = vals.get("mail_server_id")
            server = self.env["ir.mail_server"].browse(server_id).exists() if server_id else self.env["ir.mail_server"].browse()
            if not server or server.sender_pool not in ("signup", "order"):
                continue

            pool = server.sender_pool
            if pool == "signup" or vals.get("model") in self._AFFINITY_MODELS:
                remembered = self._remembered_customer_sender(partner, today, pool)
                if remembered:
                    self._apply_sender_values(vals, remembered)
                    selected_for_partner[(pool, partner.id)] = remembered
                    pending_affinity[pool][partner.id] = remembered
                else:
                    pool_indexes[pool].append(vals)

        # Second pass: allocate all new pool mails in batch. The cursor is
        # advanced once per pool instead of once per mail.
        for pool, pending_vals in pool_indexes.items():
            if not pending_vals:
                continue
            servers = self.env["ir.mail_server"]._sender_pool_servers(pool)
            if not servers:
                continue

            # A customer gets one sender for the day. Reuse that sender for
            # every mail in this create batch belonging to the same customer.
            groups = []
            group_seen = set()
            ungrouped = []
            for vals in pending_vals:
                partner = partner_cache.get(id(vals))
                if partner:
                    key = partner.id
                    if key not in group_seen:
                        group_seen.add(key)
                        groups.append((key, partner))
                else:
                    ungrouped.append(vals)

            required = len(groups) + len(ungrouped)
            selected_servers = list(self.env["ir.mail_server"].browse())
            if required:
                selected_servers = list(
                    self.env["ir.mail_server"]
                    ._select_sender_servers(pool, required)
                )

            cursor = 0
            for partner_id, partner in groups:
                selected = pending_affinity[pool].get(partner_id)
                if not selected:
                    selected = selected_servers[cursor]
                    cursor += 1
                    pending_affinity[pool][partner_id] = selected
                    partner.sudo().write({
                        "signup_sender_id" if pool == "signup" else "order_sender_id": selected.id,
                        "signup_sender_date" if pool == "signup" else "order_sender_date": today,
                    })
                for vals in pending_vals:
                    if partner_cache.get(id(vals)) and partner_cache[id(vals)].id == partner_id:
                        self._apply_sender_values(vals, selected)

            for vals in ungrouped:
                selected = selected_servers[cursor]
                cursor += 1
                self._apply_sender_values(vals, selected)

        return super().create(vals_list)

    @api.model
    def _partner_from_values(self, model, res_id, recipient_ids=None):
        if model and res_id and model in self.env:
            record = self.env[model].browse(res_id).exists()
            if record:
                partner = getattr(record, "partner_id", False)
                if partner:
                    return partner.commercial_partner_id or partner
                if model == "res.users" and record.partner_id:
                    return record.partner_id.commercial_partner_id or record.partner_id
        if recipient_ids:
            # create() values may contain [(6, 0, ids)] or [(4, id)] commands.
            ids = []
            for command in recipient_ids:
                if command[0] == 6:
                    ids.extend(command[2])
                elif command[0] == 4:
                    ids.append(command[1])
            if ids:
                partner = self.env["res.partner"].browse(ids[:1]).exists()
                return partner.commercial_partner_id if partner else partner
        return self.env["res.partner"].browse()

    @staticmethod
    def _apply_sender_values(vals, server):
        sender = (server.sender_email or server.smtp_user or "").strip()
        if not sender or "@" not in sender:
            return
        name, _address = parseaddr(vals.get("email_from") or "")
        if not name:
            name = server.name or ""
        email_from = formataddr((name, sender)) if name else sender
        vals["mail_server_id"] = server.id
        vals["email_from"] = email_from
        vals["reply_to"] = email_from

    def _target_partner(self):
        self.ensure_one()
        return self._partner_from_values(self.model, self.res_id, False)

    def _is_customer_affinity_mail(self):
        self.ensure_one()
        return self.model in self._AFFINITY_MODELS

    def _remembered_customer_sender(self, partner, today, pool=None):
        if not partner:
            return self.env["ir.mail_server"].browse()

        if pool == "signup":
            sender = partner.signup_sender_id
            if sender and partner.signup_sender_date == today and sender.active and sender.sender_pool == "signup":
                return sender
            return self.env["ir.mail_server"].browse()

        sender = partner.order_sender_id
        if sender and partner.order_sender_date == today and sender.active and sender.sender_pool == "order":
            return sender
        return self.env["ir.mail_server"].browse()

    def _set_from_server_sender(self, server):
        """Legacy helper retained for compatibility; no queue-time write path."""
        self.ensure_one()
        sender = (server.sender_email or server.smtp_user or "").strip()
        if not sender or "@" not in sender:
            return
        name, _address = parseaddr(self.email_from or "")
        if not name:
            name = server.name or ""
        email_from = formataddr((name, sender)) if name else sender
        if self.email_from != email_from or self.reply_to != email_from:
            self.with_context(rate_limit_internal=True).write({
                "email_from": email_from,
                "reply_to": email_from,
            })

    def _sync_pool_sender_before_send(self):
        """Compatibility hook; sender is already fixed during create()."""
        return True

    def _apply_selected_sender(self, partner, today, selected):
        """Compatibility helper for callers outside create()."""
        if not selected:
            return
        vals = {
            "email_from": self.email_from,
            "reply_to": self.reply_to,
        }
        self._apply_sender_values(vals, selected)
        vals.pop("mail_server_id", None)
        self.with_context(rate_limit_internal=True).write(vals)
        if partner:
            if selected.sender_pool == "signup":
                partner.sudo().write({"signup_sender_id": selected.id, "signup_sender_date": today})
            elif selected.sender_pool == "order":
                partner.sudo().write({"order_sender_id": selected.id, "order_sender_date": today})

    def _apply_sender_pool(self):
        """Compatibility no-op; sender selection now happens in create()."""
        return True

    def _rate_limit_recipients(self):
        self.ensure_one()
        recipients = []
        if self.email_to:
            recipients.extend(tools.mail.email_normalize_all(self.email_to))
        if self.email_cc:
            recipients.extend(tools.mail.email_normalize_all(self.email_cc))
        for partner in self.recipient_ids:
            recipients.extend(tools.mail.email_normalize_all(partner.email or ""))
        return list(dict.fromkeys(recipients))

    def _rate_limit_send(self, auto_commit=False, raise_exception=False, post_send_callback=None):
        allowed = self.browse()
        for mail in self:
            server = mail.mail_server_id
            if not server or not server.rate_limit_enabled:
                allowed |= mail
                continue
            ok, next_at = self.env["email.rate.limit.state"].sudo().reserve(
                server, 1, mail._rate_limit_recipients()
            )
            if ok:
                allowed |= mail
            else:
                mail.write({"scheduled_date": next_at, "state": "outgoing"})
        if allowed:
            return super(MailMail, allowed).send(
                auto_commit=auto_commit,
                raise_exception=raise_exception,
                post_send_callback=post_send_callback,
            )
        return True

    def send(self, auto_commit=False, raise_exception=False, post_send_callback=None):
        return self._rate_limit_send(
            auto_commit=auto_commit,
            raise_exception=raise_exception,
            post_send_callback=post_send_callback,
        )
