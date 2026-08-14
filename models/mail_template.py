from odoo import models


class MailTemplate(models.Model):
    _inherit = "mail.template"

    def send_mail(self, res_id, force_send=False, raise_exception=False, email_values=None, email_layout_xmlid=False):
        """Route template force-send into the dedicated instant queue.

        Manual Send from the Emails screen calls mail.mail directly and therefore
        keeps its explicit operator-driven behavior. The shared outgoing-server
        gate still protects every actual SMTP send.
        """
        if not force_send or self.env.context.get("skip_email_rate_queue"):
            return super().send_mail(
                res_id,
                force_send=force_send,
                raise_exception=raise_exception,
                email_values=email_values,
                email_layout_xmlid=email_layout_xmlid,
            )

        mail_id = super().send_mail(
            res_id,
            force_send=False,
            raise_exception=raise_exception,
            email_values=email_values,
            email_layout_xmlid=email_layout_xmlid,
        )
        mail = self.env["mail.mail"].browse(mail_id).exists()
        if mail:
            self.env["email.rate.queue"].enqueue(mail)
        return mail_id
