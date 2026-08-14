from datetime import datetime, timedelta, timezone

from odoo import api, fields, models
from odoo.exceptions import UserError


class EmailRateLimitState(models.Model):
    _name = "email.rate.limit.state"
    _description = "Outgoing Mail Server Rate Limit State"
    _rec_name = "mail_server_id"

    mail_server_id = fields.Many2one("ir.mail_server", required=True, ondelete="cascade", index=True)
    window_start = fields.Datetime(required=True, index=True)
    sent_count = fields.Integer(default=0)

    _sql_constraints = [
        ("server_unique", "unique(mail_server_id)", "There must be one rate-limit state per mail server."),
    ]

    @api.model
    def reserve(self, server, count=1):
        if not server.rate_limit_enabled or server.rate_limit_count <= 0:
            return True, None

        now = fields.Datetime.now()
        window = max(server.rate_limit_window, 1)
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        current = now.replace(tzinfo=timezone.utc)
        start_seconds = int((current - epoch).total_seconds()) // window * window
        window_start = datetime.fromtimestamp(start_seconds, tz=timezone.utc).replace(tzinfo=None)

        state = self.search([("mail_server_id", "=", server.id)], limit=1)
        if not state:
            state = self.create({"mail_server_id": server.id, "window_start": window_start})
        else:
            state = state.with_for_update() if hasattr(state, "with_for_update") else state
            if state.window_start != window_start:
                state.write({"window_start": window_start, "sent_count": 0})

        if state.sent_count + count > server.rate_limit_count:
            next_window = window_start + timedelta(seconds=window)
            return False, fields.Datetime.to_string(next_window)

        state.write({"sent_count": state.sent_count + count})
        return True, None


class EmailRateQueue(models.Model):
    _name = "email.rate.queue"
    _description = "Instant Email Queue"
    _order = "priority desc, scheduled_at, id"

    mail_id = fields.Many2one("mail.mail", required=True, ondelete="cascade", index=True)
    mail_server_id = fields.Many2one("ir.mail_server", required=True, index=True)
    priority = fields.Integer(default=10)
    state = fields.Selection(
        [("pending", "Pending"), ("processing", "Processing"), ("done", "Done"), ("failed", "Failed")],
        default="pending",
        index=True,
    )
    scheduled_at = fields.Datetime(default=fields.Datetime.now, index=True)
    retry_count = fields.Integer(default=0)
    fallback_used = fields.Boolean(default=False)
    error_message = fields.Text()

    _sql_constraints = [
        ("mail_unique", "unique(mail_id)", "An email can only have one instant queue item."),
    ]

    @api.model
    def enqueue(self, mail, mail_server=None, priority=10):
        server = mail_server or mail.mail_server_id
        if not server:
            raise UserError("An outgoing mail server is required for the instant email queue.")
        existing = self.search([("mail_id", "=", mail.id)], limit=1)
        if existing:
            return existing
        return self.create({
            "mail_id": mail.id,
            "mail_server_id": server.id,
            "priority": priority,
        })

    @api.model
    def _cron_process(self):
        now = fields.Datetime.now()
        items = self.search([
            ("state", "=", "pending"),
            ("scheduled_at", "<=", now),
        ], order="priority desc, scheduled_at, id", limit=100)
        for item in items:
            item._process_one()

    def _process_one(self):
        self.ensure_one()
        if self.state != "pending":
            return
        self.state = "processing"
        allowed, next_at = self.env["email.rate.limit.state"].reserve(self.mail_server_id)
        if not allowed:
            self.write({"state": "pending", "scheduled_at": next_at})
            return

        try:
            self.mail_id.with_context(rate_limit_queue=True)._send([self.mail_server_id.id])
            self.write({"state": "done", "error_message": False})
        except Exception as exc:
            self._handle_send_error(exc)

    def _handle_send_error(self, exc):
        self.ensure_one()
        message = str(exc)
        rate_limited = any(token in message.lower() for token in (
            "frequency limited", "rate limit", "too many requests", "429",
        ))
        if rate_limited:
            if self.retry_count < self.mail_server_id.rate_limit_max_retries:
                self.write({
                    "state": "pending",
                    "retry_count": self.retry_count + 1,
                    "scheduled_at": fields.Datetime.now() + timedelta(
                        seconds=max(self.mail_server_id.rate_limit_retry_delay, 1)
                    ),
                    "error_message": message,
                })
                return
            fallback = self.mail_server_id.fallback_server_id if self.mail_server_id.fallback_enabled else False
            if fallback and not self.fallback_used:
                self.write({
                    "state": "pending",
                    "mail_server_id": fallback.id,
                    "fallback_used": True,
                    "retry_count": 0,
                    "scheduled_at": fields.Datetime.now(),
                    "error_message": message,
                })
                return
        self.write({"state": "failed", "error_message": message})
