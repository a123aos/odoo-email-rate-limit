from email.utils import formataddr, parseaddr

from odoo import api, fields, models, tools


class MailMail(models.Model):
    _inherit = "mail.mail"

    # Customer sender affinity applies to the commercial/order communication
    # chain, not to unrelated account/system mail (for example password reset).
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
        """Whether this mail belongs to the business sender-affinity chain."""
        self.ensure_one()
        return self.model in self._AFFINITY_MODELS

    def _remembered_customer_sender(self, partner, today):
        """Return today's signup/order sender for a customer, if any."""
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
        """Keep the template display name but use the selected server address.

        Templates may deliberately contain a fallback such as
        ``Company <order@aritrz.com>``. Once a pool server has been selected,
        the actual address must come from that server instead of remaining a
        fixed template address. No pool address is hard-coded here.
        """
        self.ensure_one()
        sender = server.smtp_user
        if not sender:
            return

        name, _address = parseaddr(self.email_from or "")
        if not name:
            name = server.name or ""
        self.with_context(rate_limit_internal=True).write({
            "email_from": formataddr((name, sender)) if name else sender,
        })

    def _apply_selected_sender(self, partner, today, selected):
        if not selected:
            return
        self.with_context(rate_limit_internal=True).write({"mail_server_id": selected.id})
        self._set_from_server_sender(selected)

        # The sender affinity is stored on the customer so all subsequent
        # eligible business emails today reuse exactly this server/address.
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
        """Resolve sender pools using Customer + day affinity.

        Signup and Order pools establish the sender affinity. Once a customer
        has one of those senders for the current day, subsequent emails in the
        business communication chain reuse it even when their template has no
        outgoing server or uses a different pool setting.

        Unrelated account/system mail is deliberately excluded.
        """
        for mail in self:
            partner = mail._target_partner()
            today = fields.Date.context_today(mail)

            if not mail._is_customer_affinity_mail():
                continue

            # Existing customer affinity always wins over the current template
            # selection for the rest of the day.
            remembered = mail._remembered_customer_sender(partner, today)
            if remembered:
                mail.with_context(rate_limit_internal=True).write({"mail_server_id": remembered.id})
                mail._set_from_server_sender(remembered)
                continue

            server = mail.mail_server_id
            if not server or server.sender_pool == "none":
                continue

            if server.sender_pool == "signup":
                selected = self.env["ir.mail_server"]._select_sender_from_pool("signup")
                mail._apply_selected_sender(partner, today, selected)
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
            return super(MailMail, allowed).send(
                auto_commit=auto_commit,
                raise_exception=raise_exception,
                post_send_callback=post_send_callback,
            )
        return True

    def send(self, auto_commit=False, raise_exception=False, post_send_callback=None):
        """Rate-limit every sending path, including manual Send Now."""
        return self._rate_limit_send(
            auto_commit=auto_commit,
            raise_exception=raise_exception,
            post_send_callback=post_send_callback,
        )
