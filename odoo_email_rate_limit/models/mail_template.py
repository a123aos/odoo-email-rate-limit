from odoo import models


class MailTemplate(models.Model):
    _inherit = "mail.template"

    def send_mail(self, res_id, force_send=False, raise_exception=False, email_values=None, email_layout_xmlid=False):
        """Turn template force-send into an item in the dedicated instant queue.

        Manual sends from the Odoo Emails screen are not routed here and therefore
        keep Odoo's native manual-send behavior. The final SMTP rate gate is still
        enforced by mail.mail.send().
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
        mail = self.env["mail.mail"].browse(mail_id)
        self.env["email.rate.queue"].enqueue(mail)
        return mail_id
