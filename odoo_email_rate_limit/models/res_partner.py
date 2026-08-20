from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    signup_sender_id = fields.Many2one(
        "ir.mail_server",
        string="Signup Email Server",
        copy=False,
        readonly=True,
    )
    signup_sender_date = fields.Date(string="Signup Email Date", copy=False, readonly=True)

    @api.model
    def _set_signup_sender(self, partner, server):
        if partner and server:
            partner.sudo().write({
                "signup_sender_id": server.id,
                "signup_sender_date": fields.Date.context_today(self),
            })
