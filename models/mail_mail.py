import datetime
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class MailMail(models.Model):
    _inherit = "mail.mail"

    rate_limit_retry_count = fields.Integer(
        string="Rate-Limit Retries", default=0, copy=False, readonly=True
    )
    rate_limit_fallback_used = fields.Boolean(
        string="Fallback Used", default=False, copy=False, readonly=True
    )
    rate_limit_server_id = fields.Many2one(
        "ir.mail_server", string="Rate-Limit Server", copy=False, readonly=True
    )

    def _rate_limit_is_exempt(self):
        return bool(self.env.context.get("rate_limit_bypass"))

    def _rate_limit_prepare_batch(self, mail_server, batch_ids):
        """Reserve the current one-minute window for a batch.

        The outgoing server owns the quota, so all mail paths using that server
        share it. Only the current window is reserved here. Anything that does
        not fit is deferred to the next minute; it is intentionally not counted
        in advance, so concurrent workers cannot accidentally double-reserve a
        future window.
        """
        if (
            not mail_server
            or not mail_server.rate_limit_enabled
            or self._rate_limit_is_exempt()
        ):
            return self.browse(batch_ids)

        mails = self.browse(batch_ids).filtered(lambda mail: mail.state == "outgoing")
        if not mails:
            return mails

        current_window = fields.Datetime.now().replace(second=0, microsecond=0)
        self.env.cr.execute(
            """
                SELECT rate_limit_window, rate_limit_count
                  FROM ir_mail_server
                 WHERE id = %s
                 FOR UPDATE
            """,
            [mail_server.id],
        )
        row = self.env.cr.fetchone()
        stored_window = fields.Datetime.to_datetime(row[0]) if row and row[0] else False
        current_count = int(row[1] or 0) if row else 0
        if stored_window != current_window:
            current_count = 0

        limit = mail_server.rate_limit_per_minute
        allowed = self.browse()
        delayed = self.browse()
        next_window = current_window + datetime.timedelta(minutes=1)

        for mail in mails.sorted(lambda record: (record.create_date, record.id)):
            if current_count < limit:
                allowed |= mail
                current_count += 1
                mail.write({
                    "rate_limit_server_id": mail_server.id,
                    "scheduled_date": False,
                })
            else:
                delayed |= mail
                mail.write({
                    "rate_limit_server_id": mail_server.id,
                    "scheduled_date": next_window,
                })

        mail_server.sudo().write({
            "rate_limit_window": current_window,
            "rate_limit_count": current_count,
        })

        if delayed:
            cron = self.env.ref(
                "mail.ir_cron_mail_scheduler_action", raise_if_not_found=False
            )
            if cron:
                cron._trigger(next_window + datetime.timedelta(seconds=1))
            _logger.info(
                "Email rate limit: server %s allowed %s and deferred %s mail(s) to %s",
                mail_server.display_name,
                len(allowed),
                len(delayed),
                next_window,
            )

        return allowed

    def _split_by_mail_configuration(self):
        for mail_server_id, alias_domain_id, smtp_from, batch_ids in super()._split_by_mail_configuration():
            mail_server = (
                self.env["ir.mail_server"].browse(mail_server_id).exists()
                if mail_server_id
                else self.env["ir.mail_server"]
            )
            if mail_server and mail_server.rate_limit_enabled and not self._rate_limit_is_exempt():
                allowed = self._rate_limit_prepare_batch(mail_server, batch_ids)
                if not allowed:
                    continue
                yield mail_server_id, alias_domain_id, smtp_from, allowed.ids
            else:
                yield mail_server_id, alias_domain_id, smtp_from, batch_ids

    @staticmethod
    def _is_rate_limit_error(reason):
        text = (reason or "").lower()
        return any(
            marker in text
            for marker in (
                "sender frequency limited",
                "rate limit",
                "rate-limit",
                "too many requests",
                "too many messages",
                "throttl",
                "429",
            )
        )

    def _handle_rate_limit_failures(self, mails, mail_server):
        if not mail_server or self.env.context.get("rate_limit_no_fallback"):
            return

        failed = mails.filtered(
            lambda mail: (
                mail.rate_limit_server_id == mail_server
                and mail.state == "exception"
                and self._is_rate_limit_error(mail.failure_reason)
            )
        )
        if not failed:
            return

        retry = failed.filtered(
            lambda mail: (
                not mail.rate_limit_fallback_used
                and mail.rate_limit_retry_count < mail_server.fallback_max_retries
            )
        )
        for mail in retry:
            mail.write({
                "state": "outgoing",
                "scheduled_date": fields.Datetime.now()
                + datetime.timedelta(seconds=mail_server.fallback_retry_delay),
                "rate_limit_retry_count": mail.rate_limit_retry_count + 1,
            })

        exhausted = failed - retry
        if not exhausted:
            return
        if not mail_server.fallback_enabled or not mail_server.fallback_server_id:
            return

        fallback = mail_server.fallback_server_id
        exhausted.write({
            "state": "outgoing",
            "scheduled_date": fields.Datetime.now(),
            "mail_server_id": fallback.id,
            "rate_limit_server_id": fallback.id,
            "rate_limit_fallback_used": True,
            "rate_limit_retry_count": 0,
        })
        _logger.warning(
            "Primary mail server %s remained rate-limited; %s mail(s) moved to fallback %s.",
            mail_server.display_name,
            len(exhausted),
            fallback.display_name,
        )
        # The fallback send still passes through the fallback server's own
        # limiter. This context only prevents recursive fallback.
        exhausted.with_context(rate_limit_no_fallback=True).send()

    def send(self, auto_commit=False, raise_exception=False, post_send_callback=None):
        result = super().send(
            auto_commit=auto_commit,
            raise_exception=raise_exception,
            post_send_callback=post_send_callback,
        )
        if not self._rate_limit_is_exempt() and not self.env.context.get("rate_limit_no_fallback"):
            fresh = self.browse(self.ids).exists()
            for mail_server in fresh.mapped("rate_limit_server_id"):
                self._handle_rate_limit_failures(fresh, mail_server)
        return result

    def action_send_and_close(self):
        """Explicit operator action: bypass background rate limiting."""
        return super(
            MailMail, self.with_context(rate_limit_bypass=True)
        ).action_send_and_close()
