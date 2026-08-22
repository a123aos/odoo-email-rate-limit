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
        mails = super().create(vals_list)
        for mail in mails:
            mail._apply_sender_pool()
        return mails

    def _target_partner(self):
        self.ensure_one()
        if self.model and self.res_id and self.model in self.env:
            record = self.env[self.model].browse(self.res_id).exists()
            if record:
                partner = getattr(record, "partner_id", False)
                if partner:
                    return partner.commercial_partner_id or partner
                if self.model == "res.users" and record.partner_id:
                    partner = record.partner_id
                    return partner.commercial_partner_id or partner
        partner = self.recipient_ids[:1]
        return partner.commercial_partner_id if partner else partner

    def _is_customer_affinity_mail(self):
        self.ensure_one()
        return self.model in self._AFFINITY_MODELS

    def _remembered_customer_sender(self, partner, today):
        if not partner:
            return self.env["ir.mail_server"].browse()

        if partner.signup_sender_id and partner.signup_sender_date == today:
            sender = partner.signup_sender_id
            if sender.active and sender.sender_pool == "signup":
                return sender

        if partner.order_sender_id and partner.order_sender_date == today:
            sender = partner.order_sender_id
            if sender.active and sender.sender_pool == "order":
                return sender

        return self.env["ir.mail_server"].browse()

    def _set_from_server_sender(self, server):
        """Use the selected server's SMTP login as the actual From address.

        The template's address is only a fallback. This method is deliberately
        called both when the pool is selected and immediately before SMTP send,
        because Odoo can rebuild/update mail.mail values after create().
        """
        self.ensure_one()
        sender = (server.smtp_user or "").strip()
        if not sender:
            return

        name, _address = parseaddr(self.email_from or "")
        if not name:
            name = server.name or ""
        email_from = formataddr((name, sender)) if name else sender
        if self.email_from != email_from:
            self.with_context(rate_limit_internal=True).write({"email_from": email_from})

    def _sync_pool_sender_before_send(self):
        """Final guard: selected pool server always wins over template From."""
        for mail in self:
            server = mail.mail_server_id
            if server and server.sender_pool in ("signup", "order"):
                mail._set_from_server_sender(server)

    def _apply_selected_sender(self, partner, today, selected):
        if not selected:
            return
        self.with_context(rate_limit_internal=True).write({"mail_server_id": selected.id})
        self._set_from_server_sender(selected)

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
        """Resolve Signup/Order pools using customer + day affinity."""
        for mail in self:
            partner = mail._target_partner()
            today = fields.Date.context_today(mail)
            server = mail.mail_server_id

            # Signup itself is the onboarding event, including templates whose
            # originating model is res.users.
            if server and server.sender_pool == "signup":
                remembered = self._remembered_customer_sender(partner, today)
                if remembered and remembered.sender_pool == "signup":
                    mail.with_context(rate_limit_internal=True).write({"mail_server_id": remembered.id})
                    mail._set_from_server_sender(remembered)
                else:
                    selected = self.env["ir.mail_server"]._select_sender_from_pool("signup")
                    mail._apply_selected_sender(partner, today, selected)
                continue

            # Password reset and unrelated account/system mail must not inherit
            # a customer's business sender.
            if not mail._is_customer_affinity_mail():
                continue

            # A sender already assigned today wins regardless of the current
            # business template's outgoing-server setting.
            remembered = mail._remembered_customer_sender(partner, today)
            if remembered:
                mail.with_context(rate_limit_internal=True).write({"mail_server_id": remembered.id})
                mail._set_from_server_sender(remembered)
                continue

            if not server or server.sender_pool == "none":
                continue

            if server.sender_pool == "order":
                selected = self.env["ir.mail_server"]._select_sender_from_pool("order")
                mail._apply_selected_sender(partner, today, selected)

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
            # Odoo's send path can update mail fields between create() and SMTP
            # delivery. Re-apply the selected pool sender at the final boundary.
            allowed._sync_pool_sender_before_send()
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
