from datetime import datetime, timezone

from odoo import api, fields, models


class EmailRateLimitDashboard(models.TransientModel):
    _name = "email.rate.limit.dashboard"
    _description = "Email Rate Limit Dashboard"

    mail_server_id = fields.Many2one("ir.mail_server", string="Sender", readonly=True)
    pool = fields.Selection(related="mail_server_id.sender_pool", readonly=True)
    enabled = fields.Boolean(related="mail_server_id.rate_limit_enabled", readonly=True)
    period_limit = fields.Integer(string="Emails Limit", readonly=True)
    sent_count = fields.Integer(string="Emails Used", readonly=True)
    external_limit = fields.Integer(string="External Recipients Limit", readonly=True)
    external_count = fields.Integer(string="External Recipients Used", readonly=True)
    reset_at = fields.Datetime(string="Reset At (UTC)", readonly=True)
    email_remaining = fields.Integer(string="Emails Remaining", readonly=True)
    external_remaining = fields.Integer(string="External Recipients Remaining", readonly=True)

    @api.model
    def _reset_start(self, seconds):
        seconds = max(int(seconds or 86400), 1)
        now = datetime.now(timezone.utc)
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        start = int((now - epoch).total_seconds()) // seconds * seconds
        return datetime.fromtimestamp(start, tz=timezone.utc).replace(tzinfo=None)

    @api.model
    def _snapshot(self):
        State = self.env["email.rate.limit.state"].sudo()
        rows = []
        for server in self.env["ir.mail_server"].sudo().search([("rate_limit_enabled", "=", True), ("active", "=", True)]):
            period = max(server.rate_limit_window or 86400, 1)
            reset_start = self._reset_start(period)
            state = State.search([("mail_server_id", "=", server.id)], limit=1)
            if state and state.window_start == reset_start:
                sent = state.sent_count
                external = len((state.external_recipients or {}).keys())
            else:
                sent = 0
                external = 0
            rows.append({
                "mail_server_id": server.id,
                "period_limit": max(server.rate_limit_count, 0),
                "sent_count": sent,
                "external_limit": max(server.rate_limit_external_count, 0),
                "external_count": external,
                "reset_at": fields.Datetime.to_string(reset_start),
                "email_remaining": max(server.rate_limit_count - sent, 0) if server.rate_limit_count else 0,
                "external_remaining": max(server.rate_limit_external_count - external, 0) if server.rate_limit_external_count else 0,
            })
        return rows

    @api.model
    def action_open_dashboard(self):
        rows = self._snapshot()
        records = self.create(rows)
        return {
            "type": "ir.actions.act_window",
            "name": "Email Rate Limit Dashboard",
            "res_model": self._name,
            "view_mode": "list",
            "views": [(self.env.ref("odoo_email_rate_limit.email_rate_limit_dashboard_list").id, "list")],
            "res_id": records[:1].id if len(records) == 1 else False,
            "domain": [("id", "in", records.ids)],
            "target": "current",
        }

    def action_refresh(self):
        return self.action_open_dashboard()
