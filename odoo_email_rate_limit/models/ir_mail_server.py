from odoo import api, fields, models


class IrMailServer(models.Model):
    _inherit = "ir.mail_server"

    rate_limit_enabled = fields.Boolean(string="Enable Rate Limit")
    rate_limit_count = fields.Integer(string="Emails per Window", default=450)
    rate_limit_window = fields.Integer(string="Window (seconds)", default=86400)
    rate_limit_external_count = fields.Integer(string="External Recipients per Window", default=200)
    rate_limit_org_external_count = fields.Integer(string="Organization External Recipients per Window", default=500)
    rate_limit_internal_domains = fields.Char(
        string="Internal Email Domains",
        default=lambda self: self.env.company.email.split("@", 1)[1].lower()
        if self.env.company.email and "@" in self.env.company.email else "",
        help="Comma-separated domains treated as internal.",
    )
    sender_pool = fields.Selection(
        [("none", "Fixed / No Pool"), ("signup", "Signup (Welcome)"), ("order", "Order (SO / Invoice)")],
        string="Sender Pool", default="none", required=True,
        help="Servers in the same pool are selected round-robin.",
    )
    sender_pool_sequence = fields.Integer(string="Pool Sequence", default=10)
    fallback_enabled = fields.Boolean(string="Enable Fallback")
    fallback_server_id = fields.Many2one("ir.mail_server", string="Fallback Mail Server", domain="[('id', '!=', id)]")
    rate_limit_retry_delay = fields.Integer(string="Rate-limit Retry Delay (seconds)", default=60)
    rate_limit_max_retries = fields.Integer(string="Max Rate-limit Retries", default=3)

    def _sender_pool_servers(self, pool):
        return self.sudo().search(
            [("sender_pool", "=", pool), ("active", "=", True)],
            order="sender_pool_sequence, id",
        )

    @api.model
    def _select_sender_from_pool(self, pool):
        servers = self._sender_pool_servers(pool)
        if not servers:
            return self.browse()
        return self.env["email.sender.pool.state"].sudo().select_server(pool, servers)
