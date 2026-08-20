import json
from datetime import datetime, timedelta, timezone

from odoo import api, fields, models, tools
from odoo.exceptions import UserError


class EmailRateLimitState(models.Model):
    _name = "email.rate.limit.state"
    _description = "Outgoing Mail Server Rate Limit State"
    _rec_name = "mail_server_id"

    mail_server_id = fields.Many2one("ir.mail_server", required=True, ondelete="cascade", index=True)
    window_start = fields.Datetime(required=True, index=True)
    sent_count = fields.Integer(default=0)
    external_recipients = fields.Json(default=lambda self: {})
    _server_unique = models.Constraint("UNIQUE(mail_server_id)", "There must be one rate-limit state per mail server.")

    @api.model
    def _window_start(self, seconds):
        seconds = max(int(seconds or 86400), 1)
        now = datetime.now(timezone.utc)
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        start = int((now - epoch).total_seconds()) // seconds * seconds
        return datetime.fromtimestamp(start, tz=timezone.utc).replace(tzinfo=None)

    @api.model
    def _external_recipients(self, server, recipients):
        domains = {d.strip().lower().lstrip("@").rstrip(".") for d in (server.rate_limit_internal_domains or "").split(",") if d.strip()}
        result = set()
        for email in recipients or []:
            for value in tools.mail.email_normalize_all(email or ""):
                address = value.lower().strip()
                if "@" in address and address.rsplit("@", 1)[1] not in domains:
                    result.add(address)
        return result

    @api.model
    def reserve(self, server, count=1, recipients=None):
        if not server.rate_limit_enabled or count <= 0:
            return True, None
        window = max(server.rate_limit_window, 1)
        window_start = self._window_start(window)
        table = self._table
        self.env.cr.execute(f"INSERT INTO {table} (mail_server_id,window_start,sent_count,external_recipients,create_uid,create_date,write_uid,write_date) VALUES (%s,%s,0,%s,%s,NOW(),%s,NOW()) ON CONFLICT (mail_server_id) DO NOTHING", (server.id, window_start, "{}", self.env.uid, self.env.uid))
        self.env.cr.execute(f"SELECT id,window_start,sent_count,external_recipients FROM {table} WHERE mail_server_id=%s FOR UPDATE", (server.id,))
        row = self.env.cr.fetchone()
        if not row:
            raise UserError("Unable to initialize the email rate-limit state.")
        state_id, current_start, sent_count, sender_json = row
        if current_start != window_start:
            sent_count = 0
            sender_json = {}
        sender_json = sender_json or {}
        external = self._external_recipients(server, recipients or [])
        sender_seen = set(sender_json.keys())
        new_sender_external = external - sender_seen
        org = self.env["email.rate.limit.org.state"].sudo()._lock(window_start)
        org_seen = set((org.external_recipients or {}).keys())
        new_org_external = external - org_seen
        sender_limit = max(server.rate_limit_external_count, 0)
        org_limit = max(server.rate_limit_org_external_count, 0)
        sender_ok = sent_count + count <= max(server.rate_limit_count, 0)
        sender_external_ok = len(sender_seen) + len(new_sender_external) <= sender_limit if sender_limit else True
        org_external_ok = len(org_seen) + len(new_org_external) <= org_limit if org_limit else True
        if sender_ok and sender_external_ok and org_external_ok:
            sender_json.update({email: True for email in new_sender_external})
            self.env.cr.execute(f"UPDATE {table} SET window_start=%s,sent_count=%s,external_recipients=%s,write_uid=%s,write_date=NOW() WHERE id=%s", (window_start, sent_count + count, json.dumps(sender_json), self.env.uid, state_id))
            org.external_recipients = {**org_seen, **{email: True for email in new_org_external}}
            return True, None
        return False, fields.Datetime.to_string(window_start + timedelta(seconds=window))


class EmailRateLimitOrgState(models.Model):
    _name = "email.rate.limit.org.state"
    _description = "Organization Email External Recipient Rate Limit"

    key = fields.Char(default="organization", required=True)
    window_start = fields.Datetime(required=True)
    external_recipients = fields.Json(default=lambda self: {})
    _key_unique = models.Constraint("UNIQUE(key)", "There must be one organization rate-limit state.")

    @api.model
    def _lock(self, window_start):
        self.env.cr.execute(f"INSERT INTO {self._table} (key,window_start,external_recipients,create_uid,create_date,write_uid,write_date) VALUES ('organization',%s,%s,%s,NOW(),%s,NOW()) ON CONFLICT (key) DO NOTHING", (window_start, "{}", self.env.uid, self.env.uid))
        self.env.cr.execute(f"SELECT id,window_start,external_recipients FROM {self._table} WHERE key='organization' FOR UPDATE")
        row = self.env.cr.fetchone()
        record = self.browse(row[0])
        if row[1] != window_start:
            record.write({"window_start": window_start, "external_recipients": {}})
        else:
            record.external_recipients = row[2] or {}
        return record

    @api.model
    def get_dashboard_status(self):
        State = self.env["email.rate.limit.state"].sudo()
        servers = self.env["ir.mail_server"].sudo().search([("active", "=", True), ("rate_limit_enabled", "=", True)])
        if not servers:
            return {"enabled": False, "count": 0, "limit": 0, "remaining": 0, "percent": 0, "reset_at": False}

        # Lark resets its daily quota at 00:00 UTC. The rate-limit state owns
        # the canonical UTC window calculation, so the dashboard must use it too.
        window = max(max(servers.mapped("rate_limit_window") or [86400]), 1)
        start = State._window_start(window)
        state = self.sudo().search([("key", "=", "organization")], limit=1)
        current = bool(state and state.window_start == start)
        count = len(state.external_recipients or {}) if current else 0
        limit = max(max(servers.mapped("rate_limit_org_external_count") or [500]), 0)
        reset_at = datetime.fromtimestamp(start.replace(tzinfo=timezone.utc).timestamp() + window, tz=timezone.utc)
        return {
            "enabled": True,
            "count": count,
            "limit": limit,
            "remaining": max(limit - count, 0),
            "percent": min(100, round(count * 100 / limit, 1)) if limit else 0,
            "reset_at": reset_at.isoformat(),
        }


class EmailRateQueue(models.Model):
    _name = "email.rate.queue"
    _description = "Instant Email Queue"
    _order = "priority desc, scheduled_at, id"

    mail_id = fields.Many2one("mail.mail", required=True, ondelete="cascade", index=True)
    mail_server_id = fields.Many2one("ir.mail_server", required=True, index=True)
    priority = fields.Integer(default=10)
    state = fields.Selection([("pending", "Pending"), ("processing", "Processing"), ("done", "Done"), ("failed", "Failed")], default="pending", index=True)
    scheduled_at = fields.Datetime(default=fields.Datetime.now, index=True)
    retry_count = fields.Integer(default=0)
    fallback_used = fields.Boolean(default=False)
    error_message = fields.Text()
    _mail_unique = models.Constraint("UNIQUE(mail_id)", "An email can only have one instant queue item.")

    @api.model
    def enqueue(self, mail, mail_server=None, priority=10):
        server = mail_server or mail.mail_server_id
        if not server:
            raise UserError("An outgoing mail server is required for the instant email queue.")
        existing = self.search([("mail_id", "=", mail.id)], limit=1)
        return existing or self.create({"mail_id": mail.id, "mail_server_id": server.id, "priority": priority})

    @api.model
    def _cron_process(self):
        now = fields.Datetime.now()
        for item in self.search([("state", "=", "pending"), ("scheduled_at", "<=", now)], order="priority desc, scheduled_at, id", limit=100):
            item._process_one()

    def _process_one(self):
        self.ensure_one()
        if self.state != "pending" or not self.mail_id.exists():
            self.write({"state": "done"})
            return
        self.write({"state": "processing"})
        try:
            self.mail_id.send(auto_commit=False, raise_exception=True)
            if not self.mail_id.exists() or self.mail_id.state == "sent":
                self.write({"state": "done", "error_message": False})
            elif self.mail_id.state == "outgoing":
                self.write({"state": "pending", "scheduled_at": self.mail_id.scheduled_date or fields.Datetime.now() + timedelta(minutes=1)})
            else:
                self.write({"state": "failed", "error_message": self.mail_id.failure_reason})
        except Exception as exc:
            self.write({"state": "failed", "error_message": str(exc)})
