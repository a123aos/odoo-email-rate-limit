from odoo import api, fields, models, tools


class MailMail(models.Model):
    _inherit = "mail.mail"

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
                    # Sender affinity is customer-level. Always normalize to
                    # the commercial partner so SO/invoice/contact records for
                    # the same customer share the same daily sender.
                    return partner.commercial_partner_id or partner
                if self.model == "res.users" and record.partner_id:
                    partner = record.partner_id
                    return partner.commercial_partner_id or partner
        partner = self.recipient_ids[:1]
        return partner.commercial_partner_id if partner else partner

    def _apply_sender_pool(self):
        """Resolve sender pools with one sender affinity per customer per UTC day.

        A pool rotates only when a customer has no sender recorded for the
        current day. Once selected, all emails using that pool for the same
        customer on that day reuse the selected server.
        """
        for mail in self:
            server = mail.mail_server_id
            if not server or server.sender_pool == "none":
                continue

            partner = mail._target_partner()
            today = fields.Date.context_today(mail)

            if server.sender_pool == "signup":
                selected = False
                if partner and partner.signup_sender_id and partner.signup_sender_date == today:
                    remembered = partner.signup_sender_id
                    if remembered.active and remembered.sender_pool == "signup":
                        selected = remembered

                if not selected:
                    selected = self.env["ir.mail_server"]._select_sender_from_pool("signup")
                    if selected and partner:
                        partner.sudo().write({
                            "signup_sender_id": selected.id,
                            "signup_sender_date": today,
                        })

                if selected:
                    mail.with_context(rate_limit_internal=True).write({"mail_server_id": selected.id})
                continue

            if server.sender_pool == "order":
                selected = False

                # Signup and order/invoice mail for the same customer on the
                # same UTC day share the exact signup sender when available.
                if partner and partner.signup_sender_id and partner.signup_sender_date == today:
                    remembered = partner.signup_sender_id
                    if remembered.active and remembered.sender_pool == "signup":
                        selected = remembered

                # Otherwise, reuse this customer's order sender for today.
                if not selected and partner and partner.order_sender_id and partner.order_sender_date == today:
                    remembered = partner.order_sender_id
                    if remembered.active and remembered.sender_pool == "order":
                        selected = remembered

                # Only a genuinely new customer/day consumes the next order
                # pool position.
                if not selected:
                    selected = self.env["ir.mail_server"]._select_sender_from_pool("order")
                    if selected and partner:
                        partner.sudo().write({
                            "order_sender_id": selected.id,
                            "order_sender_date": today,
                        })

                if selected:
                    mail.with_context(rate_limit_internal=True).write({"mail_server_id": selected.id})

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
