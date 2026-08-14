import datetime
import logging

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class MailMail(models.Model):
    _inherit = "mail.mail"

    rate_limit_retry_count = fields.Integer(
        string="Rate-Limit Retries",
        default=0,
        copy=False,
        readonly=True,
    )
    rate_limit_fallback_used = fields.Boolean(
        string="Fallback Used",
        default=False,
        copy=False,
        readonly=True,
    )
    rate_limit_server_id = fields.Many2one(
        "ir.mail_server",
        string="Rate-Limit Server",
        copy=False,
        readonly=True,
    )

    def _rate_limit_server_for(self, mail_server_id):
        if not mail_server_id:
            return self.env["ir.mail_server"]
        return self.env["ir.mail_server"].browse(mail_server_id).exists()

    def _rate_limit_is_exempt(self):
        return bool(self.env.context.get("rate_limit_bypass"))

    def _rate_limit_prepare_batch(self, mail_server, batch_ids):
        """Reserve shared server quota and schedule overflow in Odoo's mail.mail queue."""
        if not mail_server or not mail_server.rate_limit_enabled or self._rate_limit_is_exempt():
            return self.browse(batch_ids)

        mails = self.browse(batch_ids).filtered(lambda m: m.state == "outgoing")
        if not mails:
            return mails

        # Lock the server once and reserve the whole batch incrementally.
        now = fields.Datetime.now()
        window = now.replace(second=0, microsecond=0)
        self.env.cr.execute(
            "SELECT rate_limit_window, rate_limit_count "
            "FROM ir_mail_server WHERE id = %s FOR UPDATE",
            [mail_server.id],
        )
        row = self.env.cr.fetchone()
        current_window = fields.Datetime.to_datetime(row[0]) if row and row[0] else None
        current_count = row[1] if row else 0
        if current_window != window:
            current_window = window
            current_count = 0

        allowed = self.browse()
        delayed = self.browse()
        next_window = current_window
        for mail in mails.sorted(lambda m: (m.create_date, m.id)):
            if current_count < mail_server.rate_limit_per_minute:
                allowed |= mail
                current_count += 1
                mail.write({
                    "rate_limit_server_id": mail_server.id,
                    "scheduled_date": False,
                })
            else:
                delayed |= mail
                next_window += datetime.timedelta(minutes=1)
                mail.write({
                    "scheduled_date": next_window,
                    "rate_limit_server_id": mail_server.id,
                })

        mail_server.sudo().write({
            "rate_limit_window": current_window,
            "rate_limit_count": current_count,
        })

        if delayed:
            cron = self.env.ref("mail.ir_cron_mail_scheduler_action", raise_if_not_found=False)
            if cron:
                cron._trigger(min(delayed.mapped("scheduled_date")) + datetime.timedelta(seconds=1))
            _logger.info(
                "Email rate limit: server %s allowed %s and delayed %s mail(s)",
                mail_server.display_name,
                len(allowed),
                len(delayed),
            )
        return allowed

    def _split_by_mail_configuration(self):
        for mail_server_id, alias_domain_id, smtp_from, batch_ids in super()._split_by_mail_configuration():
            mail_server = self._rate_limit_server_for(mail_server_id)
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
        markers = (
            "sender frequency limited",
            "rate limit",
            "rate-limit",
            "too many requests",
            "too many messages",
            "throttl",
            "429",
        )
        return any(marker in text for marker in markers)

    def _handle_rate_limit_failures(self, mail_server):
        if not mail_server or self.env.context.get("rate_limit_no_fallback"):
            return
        failed = self.filtered(
            lambda m: m.state == "exception" and self._is_rate_limit_error(m.failure_reason)
        )
        if not failed:
            return

        retry = failed.filtered(
            lambda m: not m.rate_limit_fallback_used
            and m.rate_limit_retry_count < mail_server.fallback_max_retries
        )
        if retry:
            retry.write({
                "state": "outgoing",
                "scheduled_date": fields.Datetime.now()
                + datetime.timedelta(seconds=mail_server.fallback_retry_delay),
                "rate_limit_retry_count": 0 + 1,
                "rate_limit_server_id": mail_server.id,
            })
            _logger.warning(
                "Primary mail server %s rate-limited %s mail(s); scheduled retry.",
                mail_server.display_name,
                len(retry),
            )

        exhausted = failed - retry
        if not exhausted or not mail_server.fallback_enabled or not mail_server.fallback_server_id:
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
        _logger.error(
            "Primary mail server %s remained rate-limited; %s mail(s) moved to fallback %s.",
            mail_server.display_name,
            len(exhausted),
            fallback.display_name,
        )

        # Send the fallback batch now, while still respecting the fallback server's
        # own rate limit. Never recursively fallback from fallback.
        exhausted.with_context(rate_limit_no_fallback=True).send()

    def send(self, auto_commit=False, raise_exception=False, post_send_callback=None):
        result = super().send(
            auto_commit=auto_commit,
            raise_exception=raise_exception,
            post_send_callback=post_send_callback,
        )
        if not self._rate_limit_is_exempt() and not self.env.context.get("rate_limit_no_fallback"):
            # A mail can have an explicitly assigned server, which is the safest source
            # for fallback. For default-server mails, rate_limit_server_id records the
            # resolved primary server during reservation.
            for mail_server in self.mapped("rate_limit_server_id"):
                if mail_server:
                    self._handle_rate_limit_failures(mail_server)
        return result

    def action_send_and_close(self):
        """Manual send is an explicit operator action and bypasses background throttling."""
        return super(MailMail, self.with_context(rate_limit_bypass=True)).action_send_and_close()
