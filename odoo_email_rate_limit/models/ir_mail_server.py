from datetime import datetime, timezone

from odoo import api, fields, models

from .sender_pool import EmailSenderPoolState


class IrMailServer(models.Model):
    _inherit = "ir.mail_server"

    rate_limit_enabled = fields.Boolean(string="Enable Rate Limit")
    rate_limit_count = fields.Integer(string="Emails per Reset Period", default=450, help="Maximum emails allowed for this sender during the reset period. For Lark daily limits, the period resets at 00:00 UTC.")
    rate_limit_window = fields.Integer(string="Reset Period (seconds)", default=86400, help="Rate-limit period in seconds. With the default 86400 seconds, the counter is aligned to UTC calendar days and resets at 00:00 UTC (Lark).")
    rate_limit_external_count = fields.Integer(string="External Recipients per Reset Period", default=200, help="Maximum unique external recipients for this sender during the reset period. With a 86400-second period, resets to 00:00 UTC.")
    rate_limit_org_external_count = fields.Integer(string="Organization External Recipients per Reset Period", default=500, help="Maximum unique external recipients across the organization during the reset period. With a 86400-second period, resets to 00:00 UTC.")
    rate_limit_internal_domains = fields.Char(string="Internal Email Domains", default=lambda self: self.env.company.email.split("@", 1)[1].lower() if self.env.company.email and "@" in self.env.company.email else "", help="Comma-separated domains treated as internal.")
    sender_pool = fields.Selection([("none", "Fixed / No Pool"), ("signup", "Signup (Welcome)"), ("order", "Order (SO / Invoice)")], string="Sender Pool", default="none", required=True, help="Servers in the same pool are selected round-robin.")
    sender_pool_sequence = fields.Integer(string="Pool Sequence", default=10)
    sender_email = fields.Char(string="Sender Address", help="Actual From address used when this server is selected by a sender pool. If empty, an email-formatted SMTP username is used as a compatibility fallback.")
    fallback_enabled = fields.Boolean(string="Enable Fallback")
    fallback_server_id = fields.Many2one("ir.mail_server", string="Fallback Mail Server", domain="[('id', '!=', id)]")
    rate_limit_retry_delay = fields.Integer(string="Rate-limit Retry Delay (seconds)", default=60)
    rate_limit_max_retries = fields.Integer(string="Max Rate-limit Retries", default=3)

    def _sender_pool_servers(self, pool):
        return self.sudo().search([("sender_pool", "=", pool), ("active", "=", True)], order="sender_pool_sequence, id")

    @api.model
    def _select_sender_servers(self, pool, count):
        servers = self._sender_pool_servers(pool)
        if not servers or count <= 0:
            return []
        return EmailSenderPoolState(self.env).select_servers(pool, servers, count)

    @api.model
    def _select_sender_from_pool(self, pool):
        selected = self._select_sender_servers(pool, 1)
        return selected[0] if selected else self.browse()

    @api.model
    def get_rate_limit_dashboard(self):
        State = self.env["email.rate.limit.state"].sudo()
        result = []
        for server in self.sudo().search([("active", "=", True), ("rate_limit_enabled", "=", True)], order="sequence, id"):
            state = State.search([("mail_server_id", "=", server.id)], limit=1)
            window = max(server.rate_limit_window or 86400, 1)
            start = State._window_start(window)
            reset_at = datetime.fromtimestamp(start.replace(tzinfo=timezone.utc).timestamp() + window, tz=timezone.utc)
            current = bool(state and state.window_start == start)
            sent = state.sent_count if current else 0
            external = len(state.external_recipients or {}) if current else 0
            email_limit = max(server.rate_limit_count, 0)
            external_limit = max(server.rate_limit_external_count, 0)
            selection = dict(server._fields["sender_pool"].selection)
            result.append({
                "id": server.id,
                "name": server.name,
                "pool_label": selection.get(server.sender_pool, server.sender_pool),
                "sent_count": sent,
                "email_limit": email_limit,
                "email_remaining": max(email_limit - sent, 0) if email_limit else 0,
                "email_percent": min(100, round(sent * 100 / email_limit, 1)) if email_limit else 0,
                "external_count": external,
                "external_limit": external_limit,
                "external_remaining": max(external_limit - external, 0) if external_limit else 0,
                "external_percent": min(100, round(external * 100 / external_limit, 1)) if external_limit else 0,
                "reset_at": reset_at.isoformat(),
            })
        return result
