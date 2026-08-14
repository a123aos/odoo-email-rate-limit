from odoo import api, fields, models


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
            # Let Odoo's normal server selection happen when send() is called.
            server = self.env["ir.mail_server"].search([], order="sequence, id", limit=1)
        if not server:
            return self.browse()
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
        if self.state != "pending" or not self.mail_id.exists():
            self.write({"state": "done"})
            return

        self.write({"state": "processing"})
        mail = self.mail_id
        try:
            mail.with_context(rate_limit_queue=True).send(auto_commit=False, raise_exception=False)
        except Exception as exc:
            self.write({"state": "failed", "error_message": str(exc)})
            return

        mail.invalidate_recordset(["state", "scheduled_date", "failure_reason", "mail_server_id"])
        if not mail.exists():
            self.write({"state": "done", "error_message": False})
            return

        if mail.state == "sent":
            self.write({"state": "done", "error_message": False})
        elif mail.state == "outgoing":
            # The shared outgoing-server gate deferred this message to a later
            # minute. Keep the custom queue item aligned with mail.mail.
            self.write({
                "state": "pending",
                "scheduled_at": mail.scheduled_date or fields.Datetime.now(),
                "error_message": mail.failure_reason or False,
            })
        else:
            self.write({
                "state": "failed",
                "error_message": mail.failure_reason or "Email delivery failed.",
            })
