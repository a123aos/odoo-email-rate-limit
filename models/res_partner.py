from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    email_sender_pool = fields.Selection([
        ('signup1', 'Signup 1'),
        ('signup2', 'Signup 2'),
        ('order1', 'Order 1'),
        ('order2', 'Order 2'),
    ], string='Email Sender Pool', copy=False, index=True,
       help='Sender pool assigned for the current UTC day. It is recalculated after the daily reset.')
    email_sender_pool_date = fields.Date(
        string='Email Sender Pool Date', copy=False, index=True,
        help='UTC date on which Email Sender Pool was assigned. The assignment resets at 00:00 UTC.')
