from odoo import api, fields, models


class IrMailServer(models.Model):
    _inherit = "ir.mail_server"

    rate_limit_enabled = fields.Boolean(
        string="Enable Rate Limit",
        default=False,
        help="Limit emails sent through this outgoing mail server.",
    )
    rate_limit_per_minute = fields.Integer(
        string="Emails / Minute",
        default=50,
        help="Maximum mail.mail records reserved for this server in one UTC minute.",
    )
    rate_limit_window = fields.Datetime(
        string="Rate Limit Window",
        readonly=True,
        copy=False,
    )
    rate_limit_count = fields.Integer(
        string="Rate Limit Count",
        readonly=True,
        copy=False,
    )
    fallback_enabled = fields.Boolean(
        string="Enable Fallback",
        default=False,
        help="Retry rate-limited deliveries through the configured fallback server.",
    )
    fallback_server_id = fields.Many2one(
        "ir.mail_server",
        string="Fallback Server",
        domain="[('id', '!=', id)]",
        help="Outgoing mail server used after repeated primary rate-limit responses.",
    )
    fallback_max_retries = fields.Integer(
        string="Primary Rate-Limit Retries",
        default=3,
        help="Number of rate-limit retries before switching to the fallback server.",
    )
    fallback_retry_delay = fields.Integer(
        string="Retry Delay (seconds)",
        default=60,
        help="Delay before a rate-limited mail is retried.",
    )

    @api.constrains("rate_limit_per_minute", "fallback_max_retries", "fallback_retry_delay")
    def _check_rate_limit_values(self):
        for server in self:
            if server.rate_limit_per_minute < 1:
                raise ValueError("Emails / Minute must be at least 1.")
            if server.fallback_max_retries < 0:
                raise ValueError("Primary Rate-Limit Retries cannot be negative.")
            if server.fallback_retry_delay < 1:
                raise ValueError("Retry Delay must be at least 1 second.")

    def _rate_limit_reserve(self, amount=1):
        """Atomically reserve quota for this server.

        A row lock makes the quota shared across Odoo workers/processes.
        Reservation happens before SMTP connection/send, so concurrent workers
        cannot independently consume the same quota.
        """
        self.ensure_one()
        if not self.rate_limit_enabled:
            return True

        now = fields.Datetime.now()
        window = now.replace(second=0, microsecond=0)
        self.env.cr.execute(
            "SELECT rate_limit_window, rate_limit_count "
            "FROM ir_mail_server WHERE id = %s FOR UPDATE",
            [self.id],
        )
        row = self.env.cr.fetchone()
        current_window = fields.Datetime.to_datetime(row[0]) if row and row[0] else None
        current_count = row[1] if row else 0

        if current_window != window:
            current_count = 0
            current_window = window

        if current_count + amount > self.rate_limit_per_minute:
            return False

        self.sudo().write({
            "rate_limit_window": current_window,
            "rate_limit_count": current_count + amount,
        })
        return True
