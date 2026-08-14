from odoo import models


class MailMail(models.Model):
    _inherit = "mail.mail"

    def _rate_limit_send(self):
        """Return the background mails allowed by the shared server quota."""
        allowed = self.browse()
        delayed = self.browse()
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
                delayed |= delayed_batch

        return allowed, delayed

    def send(self, auto_commit=False, raise_exception=False, post_send_callback=None):
        """Limit background delivery while leaving manual Send Now untouched."""
        if not (auto_commit or self.env.context.get("rate_limit_background")):
            return super().send(
                auto_commit=auto_commit,
                raise_exception=raise_exception,
                post_send_callback=post_send_callback,
            )

        if self.env.context.get("rate_limit_already_reserved"):
            return super().send(
                auto_commit=auto_commit,
                raise_exception=raise_exception,
                post_send_callback=post_send_callback,
            )

        allowed, _delayed = self._rate_limit_send()
        if not allowed:
            return True
        return super(MailMail, allowed).send(
            auto_commit=auto_commit,
            raise_exception=raise_exception,
            post_send_callback=post_send_callback,
        )

    def send_after_commit(self):
        """Rate-limit automatic post-commit delivery."""
        return super().with_context(rate_limit_background=True).send_after_commit()
