from odoo import fields, models


class IrMailServer(models.Model):
    _inherit = 'ir.mail_server'

    sender_pool = fields.Selection([
        ('none', 'None'),
        ('signup', 'Signup'),
        ('order', 'Order'),
    ], string='Customer Sender Pool', default='none', required=True,
       help='Adds this outgoing mail server to the selected automatic customer sender pool.')
