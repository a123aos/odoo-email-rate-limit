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
        """Resolve the sender once, before mail.mail records are created.

        Daily customer affinity rules:

        * A customer who signs up today gets one sender from the signup pool.
          All signup/order/invoice/delivery emails for that customer today use
          that same sender.
        * If the customer did not sign up today, the first order transaction
          today gets one sender from the order pool. Today's order/invoice/
          delivery emails then reuse that sender.
        * Reset-password emails are intentionally outside this affinity flow;
          their template should use a fixed outgoing server, not a sender pool.

        Sender selection is done per customer/user, not per email. The chosen
        server, From and Reply-To are placed directly into create values so the
        send path does not need sender-selection writes.
        """
        today = fields.Date.context_today(self)
        partner_cache = {}
        pending_by_pool = {"signup": [], "order": []}
        affinity_to_remember = {}

        for vals in vals_list:
            partner = self._partner_from_values(
                vals.get("model"), vals.get("res_id"), vals.get("recipient_ids")
            )
            partner_cache[id(vals)] = partner

            server_id = vals.get("mail_server_id")
            server = (
                self.env["ir.mail_server"].browse(server_id).exists()
                if server_id
                else self.env["ir.mail_server"].browse()
            )
            if not server or server.sender_pool not in ("signup", "order"):
                continue

            requested_pool = server.sender_pool
            if not partner:
                pending_by_pool[requested_pool].append(vals)
                continue

            # Signup is the daily anchor. Once a customer has signed up today,
            # every transactional mail today must use that signup sender.
            signup_sender = self._remembered_customer_sender(partner, today, "signup")

            if requested_pool == "signup":
                selected = signup_sender
                if not selected:
                    pending_by_pool["signup"].append(vals)
                else:
                    self._apply_sender_values(vals, selected)
                    affinity_to_remember[("signup", partner.id)] = selected
                continue

            # Order-pool templates (SO / Invoice / Delivery / payment) first
            # inherit today's signup sender. Only customers without a signup
            # affinity today use the order pool.
            if requested_pool == "order":
                selected = signup_sender or self._remembered_customer_sender(
                    partner, today, "order"
                )
                if selected:
                    self._apply_sender_values(vals, selected)
                    pool_key = "signup" if signup_sender else "order"
                    affinity_to_remember[(pool_key, partner.id)] = selected
                else:
                    pending_by_pool["order"].append(vals)

        # Allocate senders once per unique customer/user in each pool. This is
        # user-based round-robin: 10 emails for one customer consume one pool
        # slot, not 10 pool slots.
        for pool, pending_vals in pending_by_pool.items():
            if not pending_vals:
                continue

            groups = {}
            ungrouped = []
            for vals in pending_vals:
                partner = partner_cache.get(id(vals))
                if partner:
                    groups.setdefault(partner.id, partner)
                else:
                    ungrouped.append(vals)

            needed = len(groups) + len(ungrouped)
            selected_servers = self.env["ir.mail_server"]._select_sender_servers(
                pool, needed
            )
            selected_iter = iter(selected_servers)

            for partner_id in groups:
                partner = groups[partner_id]

                # An order mail may have been queued in the same create() call
                # after a signup mail for this customer. Re-check the local
                # assignment before consuming another pool slot.
                selected = affinity_to_remember.get(("signup", partner_id))
                if not selected:
                    selected = affinity_to_remember.get(("order", partner_id))

                if not selected:
                    try:
                        selected = next(selected_iter)
                    except StopIteration:
                        selected = False
                    if selected:
                        affinity_to_remember[(pool, partner_id)] = selected

                if selected:
                    for vals in pending_vals:
                        if partner_cache.get(id(vals)) == partner:
                            # If the customer signed up today, signup wins even
                            # when these vals originated from the order pool.
                            signup_selected = affinity_to_remember.get(
                                ("signup", partner_id)
                            )
                            self._apply_sender_values(
                                vals, signup_selected or selected
                            )

            for vals in ungrouped:
                try:
                    selected = next(selected_iter)
                except StopIteration:
                    selected = False
                if selected:
                    self._apply_sender_values(vals, selected)

        mails = super().create(vals_list)

        # Persist one daily affinity per customer. Signup always wins over an
        # order affinity for the same customer/date.
        for (pool, partner_id), selected in affinity_to_remember.items():
            if not selected:
                continue
            partner = self.env["res.partner"].browse(partner_id).exists()
            if not partner:
                continue
            if pool == "signup":
                partner.sudo().write({
                    "signup_sender_id": selected.id,
                    "signup_sender_date": today,
                })
            elif pool == "order" and not self._remembered_customer_sender(
                partner, today, "signup"
            ):
                partner.sudo().write({
                    "order_sender_id": selected.id,
                    "order_sender_date": today,
                })

        return mails

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
