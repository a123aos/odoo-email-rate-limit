from collections import defaultdict
from datetime import datetime, timedelta

from odoo import api, fields, models


class MailMail(models.Model):
    _inherit = "mail.mail"

    def _rate_limit_server_groups(self):
        """Return (allowed, delayed) mail ids using each outgoing server's shared quota.

        This is intentionally applied inside mail.mail.send(), so both Odoo's native
        queue and the custom instant queue share the same server-level quota.
        """
        allowed = self.browse()
        delayed = self.browse()
        State = self.env["email.rate.limit.state"].sudo()

        for server_id, _alias_domain_id, _smtp_from, batch_ids in self._split_by_mail_configuration():
            batch = self.browse(batch_ids)
            server = self.env["ir.mail_server"].browse(server_id)
            if not server or not server.rate_limit_enabled:
                allowed |= batch
                continue

            # Reserve the whole batch only when capacity exists. This prevents a
            # partial batch from consuming quota and then being split unpredictably.
            ok, next_at = State.reserve(server, len(batch))
            if ok:
                allowed |= batch
            else:
                batch.write({"scheduled_date": next_at})
                delayed |= batch

        return allowed, delayed

    def send(self, auto_commit=False, raise_exception=False, post_send_callback=None):
        """Apply outgoing-server rate limits before delegating to Odoo's sender."""
        allowed, _delayed = self._rate_limit_server_groups()
        if not allowed:
            return True
        return super().browse(allowed.ids).send(
            auto_commit=auto_commit,
            raise_exception=raise_exception,
            post_send_callback=post_send_callback,
        )
