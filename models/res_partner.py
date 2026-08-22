from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    email_sender_pool = fields.Selection([
        ('signup1', 'Signup 1'),
        ('signup2', 'Signup 2'),
        ('order1', 'Order 1'),
        ('order2', 'Order 2'),
    ], string='Email Sender Pool', copy=False, index=True,
       help='Persistent sender pool used for this customer\'s outgoing emails.')
