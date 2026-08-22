from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    email_sender_server_id = fields.Many2one(
        'ir.mail_server', string='Email Sender Server', copy=False, index=True,
        help='Outgoing mail server assigned for this customer for the current UTC day.')
    email_sender_pool_date = fields.Date(
        string='Email Sender Pool Date', copy=False, index=True,
        help='UTC date on which the sender server was assigned. Assignment resets at 00:00 UTC.')
