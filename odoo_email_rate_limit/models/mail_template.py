from odoo import api, fields, models


class MailTemplate(models.Model):
    _inherit = "mail.template"

    rate_limit_sender = fields.Selection(
        selection="_rate_limit_sender_selection",
        string="Outgoing Mail Server",
        compute="_compute_rate_limit_sender",
        inverse="_inverse_rate_limit_sender",
        readonly=False,
        help="Select a fixed outgoing server or a sender pool. Pool members are selected automatically.",
    )

    @api.model
    def _rate_limit_sender_selection(self):
        """Return current fixed servers followed by the configured sender pools."""
        MailServer = self.env["ir.mail_server"].sudo()
        choices = []

        for server in MailServer.search(
            [
                ("active", "=", True),
                "|",
                ("sender_pool", "=", "none"),
                ("sender_pool", "=", False),
            ],
            order="sequence, id",
        ):
            choices.append((f"server:{server.id}", server.name))

        for pool, label in (("order", "Order Pool"), ("signup", "Signup Pool")):
            if MailServer.search_count(
                [("sender_pool", "=", pool), ("active", "=", True)]
            ):
                choices.append((f"pool:{pool}", label))

        return choices

    @api.model
    def get_rate_limit_sender_selection(self):
        """Return fresh sender choices for the Template dropdown.

        This is intentionally a public RPC method because the backend Selection
        metadata is loaded with the form and is not refreshed merely because an
        ir.mail_server was changed in another form.
        """
        return self._rate_limit_sender_selection()

    @api.depends("mail_server_id", "mail_server_id.sender_pool", "mail_server_id.active", "mail_server_id.name")
    def _compute_rate_limit_sender(self):
        for template in self:
            server = template.mail_server_id
            if not server or not server.active:
                template.rate_limit_sender = False
            elif server.sender_pool in ("order", "signup"):
                template.rate_limit_sender = f"pool:{server.sender_pool}"
            else:
                template.rate_limit_sender = f"server:{server.id}"

    def _inverse_rate_limit_sender(self):
        MailServer = self.env["ir.mail_server"].sudo()
        for template in self:
            value = template.rate_limit_sender
            if not value:
                template.mail_server_id = False
                continue

            kind, key = value.split(":", 1)
            if kind == "server":
                server = MailServer.browse(int(key)).exists()
                if (
                    not server
                    or not server.active
                    or server.sender_pool not in ("none", False)
                ):
                    raise ValueError("The selected outgoing mail server is no longer available.")
                template.mail_server_id = server.id
                continue

            if kind == "pool":
                servers = MailServer.search(
                    [("sender_pool", "=", key), ("active", "=", True)],
                    order="sender_pool_sequence, id",
                    limit=1,
                )
                if not servers:
                    raise ValueError("The selected sender pool has no active outgoing mail server.")
                template.mail_server_id = servers.id
                continue

            raise ValueError("Invalid outgoing mail server selection.")

    def send_mail(self, res_id, force_send=False, raise_exception=False, email_values=None, email_layout_xmlid=False):
        """Turn template force-send into an item in the dedicated instant queue.

        Manual sends from the Odoo Emails screen are not routed here and therefore
        keep Odoo's native manual-send behavior. The final SMTP rate gate is still
        enforced by mail.mail.send().
        """
        if not force_send or self.env.context.get("skip_email_rate_queue"):
            return super().send_mail(
                res_id,
                force_send=force_send,
                raise_exception=raise_exception,
                email_values=email_values,
                email_layout_xmlid=email_layout_xmlid,
            )

        mail_id = super().send_mail(
            res_id,
            force_send=False,
            raise_exception=raise_exception,
            email_values=email_values,
            email_layout_xmlid=email_layout_xmlid,
        )
        mail = self.env["mail.mail"].browse(mail_id)
        self.env["email.rate.queue"].enqueue(mail)
        return mail_id
