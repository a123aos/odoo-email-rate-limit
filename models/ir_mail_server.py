from odoo import api, fields, models
from odoo.exceptions import ValidationError


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
    rate_limit_window = fields.Datetime(string="Rate Limit Window", readonly=True, copy=False)
    rate_limit_count = fields.Integer(string="Rate Limit Count", readonly=True, copy=False)
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
                raise ValidationError("Emails / Minute must be at least 1.")
            if server.fallback_max_retries < 0:
                raise ValidationError("Primary Rate-Limit Retries cannot be negative.")
            if server.fallback_retry_delay < 1:
                raise ValidationError("Retry Delay must be at least 1 second.")

    @api.constrains("fallback_enabled", "fallback_server_id")
    def _check_fallback_server(self):
        for server in self:
            if server.fallback_enabled and not server.fallback_server_id:
                raise ValidationError("A fallback server is required when fallback is enabled.")
            if server.fallback_server_id == server:
                raise ValidationError("The fallback server must be different from the primary server.")
