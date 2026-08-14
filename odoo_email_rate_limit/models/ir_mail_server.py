from odoo import fields, models


class IrMailServer(models.Model):
    _inherit = "ir.mail_server"

    rate_limit_enabled = fields.Boolean(
        string="Enable Rate Limit",
        help="Apply a shared sending limit to all queues using this outgoing server.",
    )
    rate_limit_count = fields.Integer(
        string="Emails per Window",
        default=50,
    )
    rate_limit_window = fields.Integer(
        string="Window (seconds)",
        default=60,
    )
    fallback_enabled = fields.Boolean(string="Enable Fallback")
    fallback_server_id = fields.Many2one(
        "ir.mail_server",
        string="Fallback Mail Server",
        domain="[('id', '!=', id)]",
    )
    rate_limit_retry_delay = fields.Integer(
        string="Rate-limit Retry Delay (seconds)",
        default=60,
    )
    rate_limit_max_retries = fields.Integer(
        string="Max Rate-limit Retries",
        default=3,
    )
