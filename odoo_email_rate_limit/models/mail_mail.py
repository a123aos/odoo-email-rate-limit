from odoo import models


class MailMail(models.Model):
    _inherit = "mail.mail"

    def _rate_limit_server_groups(self):
        """Split the current send into allowed and deferred records.

        The gate is deliberately placed on mail.mail.send() so Odoo's native
        mass queue and the custom instant queue share exactly the same
        outgoing-server quota.
        """
        allowed = self.browse()
        delayed = self.browse()
        state_model = self.env["email.rate.limit.state"].sudo()

        for server_id, _alias_domain_id, _smtp_from, batch_ids in self._split_by_mail_configuration():
            batch = self.browse(batch_ids)
            server = self.env["ir.mail_server"].browse(server_id)
            if not server or not server.rate_limit_enabled:
                allowed |= batch
                continue

            ok, next_at = state_model.reserve(server, len(batch))
            if ok:
                allowed |= batch
            else:
                batch.write({"scheduled_date": next_at})
                delayed |= batch

        return allowed, delayed

    def send(self, auto_commit=False, raise_exception=False, post_send_callback=None):
        """Apply the shared outgoing-server rate gate, then use Odoo's sender."""
        allowed, _delayed = self._rate_limit_server_groups()
        if not allowed:
            return True
        return super(MailMail, allowed).send(
            auto_commit=auto_commit,
            raise_exception=raise_exception,
            post_send_callback=post_send_callback,
        )
