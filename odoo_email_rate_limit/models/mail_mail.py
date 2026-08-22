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
        """Resolve sender affinity once while creating mail.mail records.

        Daily rules:

        * Signup today: allocate one sender from the signup pool per customer.
          All signup, order, invoice and delivery mails for that customer today
          reuse that sender.
        * No signup today: the first order/invoice/delivery mail allocates one
          sender from the order pool; all such mails for that customer today
          reuse it.
        * Reset-password and other fixed-server mails are untouched.

        Pool rotation is per customer/user, not per email. Sender, From and
        Reply-To are written into the create values once; the send path never
        needs to rewrite them.
        """
        today = fields.Date.context_today(self)
        partner_by_vals = {id(vals): self._partner_from_values(
            vals.get("model"), vals.get("res_id"), vals.get("recipient_ids")
        ) for vals in vals_list}

        # Pool requests waiting for one sender per unique customer.
        pending = {"signup": {}, "order": {}}
        assignments = {}

        for vals in vals_list:
            partner = partner_by_vals[id(vals)]
            model = vals.get("model")
            server = self._server_from_values(vals)

            # Signup is identified by its explicitly configured signup-pool
            # server. Fixed res.users mails (e.g. reset password) are ignored.
            if server and server.sender_pool == "signup":
                pool = "signup"
            elif model in self._AFFINITY_MODELS:
                pool = "order"
            else:
                continue

            if not partner:
                # No customer identity means there is no daily affinity to
                # persist. Still select a pool sender for this individual mail.
                pending[pool][None] = pending[pool].get(None, []) + [vals]
                continue

            signup_sender = self._remembered_customer_sender(partner, today, "signup")
            order_sender = self._remembered_customer_sender(partner, today, "order")

            if pool == "signup":
                selected = signup_sender
                if selected:
                    self._apply_sender_values(vals, selected)
                    assignments[("signup", partner.id)] = selected
                else:
                    pending["signup"].setdefault(partner.id, []).append(vals)
                continue

            # Transactional mail always prefers today's signup affinity.
            selected = signup_sender or order_sender
            if selected:
                self._apply_sender_values(vals, selected)
                assignments[("signup" if signup_sender else "order", partner.id)] = selected
            else:
                pending["order"].setdefault(partner.id, []).append(vals)

        # Allocate one sender per unique customer in each pool. Ten emails for
        # one customer consume one pool slot, not ten slots.
        for pool in ("signup", "order"):
            groups = pending[pool]
            if not groups:
                continue

            partner_ids = [pid for pid in groups if pid is not None]
            anonymous = groups.get(None, [])
            selected_servers = iter(
                self.env["ir.mail_server"]._select_sender_servers(
                    pool, len(partner_ids) + len(anonymous)
                )
            )

            for partner_id in partner_ids:
                partner = self.env["res.partner"].browse(partner_id).exists()
                if not partner:
                    continue

                # A signup created earlier in the same batch wins over an order
                # allocation and must not consume an additional order slot.
                selected = assignments.get(("signup", partner_id))
                if not selected:
                    selected = assignments.get(("order", partner_id))
                if not selected:
                    try:
                        selected = next(selected_servers)
                    except StopIteration:
                        selected = False
                    if selected:
                        key = (pool, partner_id)
                        assignments[key] = selected

                if not selected:
                    continue

                for vals in groups[partner_id]:
                    # Signup wins even when the pending mail originated from
                    # an order-pool template.
                    signup_selected = assignments.get(("signup", partner_id))
                    self._apply_sender_values(vals, signup_selected or selected)

            for vals in anonymous:
                try:
                    selected = next(selected_servers)
                except StopIteration:
                    selected = False
                if selected:
                    self._apply_sender_values(vals, selected)

        mails = super().create(vals_list)

        # Persist the daily affinity after successful mail creation. Signup is
        # always the higher-priority affinity.
        Partner = self.env["res.partner"]
        for (pool, partner_id), selected in assignments.items():
            if not selected or not partner_id:
                continue
            partner = Partner.browse(partner_id).exists()
            if not partner:
                continue
            if pool == "signup":
                partner.sudo().write({
                    "signup_sender_id": selected.id,
                    "signup_sender_date": today,
                })
            elif not self._remembered_customer_sender(partner, today, "signup"):
                partner.sudo().write({
                    "order_sender_id": selected.id,
                    "order_sender_date": today,
                })

        return mails

    @api.model
    def _server_from_values(self, vals):
        server_id = vals.get("mail_server_id")
        if not server_id:
            return self.env["ir.mail_server"].browse()
        return self.env["ir.mail_server"].browse(server_id).exists()

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
            if (
                sender
                and partner.signup_sender_date == today
                and sender.active
                and sender.sender_pool == "signup"
            ):
                return sender
            return self.env["ir.mail_server"].browse()

        sender = partner.order_sender_id
        if (
            sender
            and partner.order_sender_date == today
            and sender.active
            and sender.sender_pool == "order"
        ):
            return sender
        return self.env["ir.mail_server"].browse()

    def _set_from_server_sender(self, server):
        """Legacy compatibility helper; normal creation no longer writes here."""
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
        """No-op compatibility hook: sender is fixed at create time."""
        return True

    def _apply_selected_sender(self, partner, today, selected):
        """Compatibility helper for external callers; not used by create()."""
        if not selected:
            return
        vals = {"email_from": self.email_from, "reply_to": self.reply_to}
        self._apply_sender_values(vals, selected)
        self.with_context(rate_limit_internal=True).write({
            "mail_server_id": selected.id,
            "email_from": vals["email_from"],
            "reply_to": vals["reply_to"],
        })
        if partner:
            if selected.sender_pool == "signup":
                partner.sudo().write({
                    "signup_sender_id": selected.id,
                    "signup_sender_date": today,
                })
            elif selected.sender_pool == "order":
                partner.sudo().write({
                    "order_sender_id": selected.id,
                    "order_sender_date": today,
                })

    def _apply_sender_pool(self):
        """Compatibility no-op: sender selection now happens in create()."""
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
