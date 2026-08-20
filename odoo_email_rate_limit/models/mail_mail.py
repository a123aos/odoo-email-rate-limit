import datetime

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
                    return partner
                if self.model == "res.users" and record.partner_id:
                    return record.partner_id
        return self.recipient_ids[:1]

    def _apply_sender_pool(self):
        for mail in self:
            server = mail.mail_server_id
            if not server or server.sender_pool == "none":
                continue
            partner = mail._target_partner()
            today = fields.Date.context_today(mail)

            # Signup: always round-robin and remember the selected server for the partner.
            if server.sender_pool == "signup":
                selected = self.env["ir.mail_server"]._select_sender_from_pool("signup")
                if selected:
                    mail.with_context(rate_limit_internal=True).write({"mail_server_id": selected.id})
                    if partner:
                        partner.sudo().write({
                            "signup_sender_id": selected.id,
                            "signup_sender_date": today,
                        })
                continue

            # SO / Invoice: if the customer signed up today, reuse that exact sender.
            if server.sender_pool == "order":
                if (
                    partner
                    and partner.signup_sender_id
                    and partner.signup_sender_date == today
                    and partner.signup_sender_id.active
                    and partner.signup_sender_id.sender_pool == "signup"
                ):
                    mail.with_context(rate_limit_internal=True).write({"mail_server_id": partner.signup_sender_id.id})
                else:
                    selected = self.env["ir.mail_server"]._select_sender_from_pool("order")
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
        delayed = self.browse()
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
                delayed |= mail
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
