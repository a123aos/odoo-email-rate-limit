from odoo import models


class MailMail(models.Model):
    _inherit = "mail.mail"

    def _send_background_with_rate_limit(self, auto_commit=False, raise_exception=False, post_send_callback=None):
        """Send background emails through the shared outgoing-server limiter.

        ``mail.mail.send()`` is intentionally not overridden. Manual "Send
        Now" therefore remains completely native to Odoo and bypasses the
        rate limiter.
        """
        allowed = self.browse()
        state_model = self.env["email.rate.limit.state"].sudo()

        for server_id, _alias_domain_id, _smtp_from, batch_ids in self._split_by_mail_configuration():
            batch = self.browse(batch_ids)
            server = self.env["ir.mail_server"].browse(server_id)
            if not server or not server.rate_limit_enabled:
                allowed |= batch
                continue

            allowed_count, next_at = state_model.reserve(server, len(batch))
            allowed_batch = batch[:allowed_count]
            delayed_batch = batch[allowed_count:]
            allowed |= allowed_batch

            if delayed_batch:
                delayed_batch.write({"scheduled_date": next_at})

        if not allowed:
            return True

        return super(MailMail, allowed).send(
            auto_commit=auto_commit,
            raise_exception=raise_exception,
            post_send_callback=post_send_callback,
        )
