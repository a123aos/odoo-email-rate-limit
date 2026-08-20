from datetime import datetime, timezone

from odoo import api, fields, models, tools


class EmailRateLimitDashboard(models.Model):
    """Read-only rate-limit dashboard backed by a SQL view."""

    _name = "email.rate.limit.dashboard"
    _description = "Email Rate Limit Dashboard"
    _auto = False
    _rec_name = "mail_server_id"

    mail_server_id = fields.Many2one("ir.mail_server", string="Sender", readonly=True)
    pool = fields.Selection(
        [
            ("none", "Fixed / No Pool"),
            ("signup", "Signup (Welcome)"),
            ("order", "Order (SO / Invoice)"),
        ],
        string="Sender Pool",
        readonly=True,
    )
    sent_count = fields.Integer(string="Emails Used", readonly=True)
    period_limit = fields.Integer(string="Emails Limit", readonly=True)
    email_remaining = fields.Integer(string="Emails Remaining", readonly=True)
    external_count = fields.Integer(string="External Recipients Used", readonly=True)
    external_limit = fields.Integer(string="External Recipients Limit", readonly=True)
    external_remaining = fields.Integer(string="External Recipients Remaining", readonly=True)
    reset_at = fields.Datetime(string="Reset At (UTC)", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE VIEW {self._table} AS (
                WITH state AS (
                    SELECT
                        s.id AS mail_server_id,
                        s.sender_pool AS pool,
                        GREATEST(s.rate_limit_count, 0) AS period_limit,
                        GREATEST(s.rate_limit_external_count, 0) AS external_limit,
                        GREATEST(s.rate_limit_window, 1) AS window_seconds,
                        COALESCE(st.sent_count, 0) AS stored_sent_count,
                        COALESCE(jsonb_object_length(st.external_recipients), 0) AS stored_external_count,
                        st.window_start AS state_window_start
                    FROM ir_mail_server s
                    LEFT JOIN email_rate_limit_state st
                        ON st.mail_server_id = s.id
                    WHERE s.rate_limit_enabled = TRUE
                      AND s.active = TRUE
                ), current_state AS (
                    SELECT *,
                        to_timestamp(
                            floor(EXTRACT(EPOCH FROM (NOW() AT TIME ZONE 'UTC')) / window_seconds)
                            * window_seconds
                        ) AT TIME ZONE 'UTC' AS current_window_start
                    FROM state
                )
                SELECT
                    ROW_NUMBER() OVER (ORDER BY mail_server_id) AS id,
                    mail_server_id,
                    pool,
                    CASE WHEN state_window_start = current_window_start
                         THEN stored_sent_count ELSE 0 END AS sent_count,
                    period_limit,
                    CASE WHEN period_limit > 0
                         THEN GREATEST(period_limit - CASE WHEN state_window_start = current_window_start
                                                          THEN stored_sent_count ELSE 0 END, 0)
                         ELSE 0 END AS email_remaining,
                    CASE WHEN state_window_start = current_window_start
                         THEN stored_external_count ELSE 0 END AS external_count,
                    external_limit,
                    CASE WHEN external_limit > 0
                         THEN GREATEST(external_limit - CASE WHEN state_window_start = current_window_start
                                                             THEN stored_external_count ELSE 0 END, 0)
                         ELSE 0 END AS external_remaining,
                    current_window_start AS reset_at
                FROM current_state
            )
        """)

    @api.model
    def action_open_dashboard(self):
        return self.env.ref("odoo_email_rate_limit.email_rate_limit_dashboard_action").read()[0]

    def action_refresh(self):
        return self.action_open_dashboard()
