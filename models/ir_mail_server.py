from odoo import fields, models


class IrMailServer(models.Model):
    _inherit = 'ir.mail_server'

    sender_pool = fields.Selection([
        ('signup', 'Signup'),
        ('order', 'Order'),
    ], string='Customer Sender Pool', default=False,
       help='Optional customer sender pool. Leave empty when this server is not part of a pool.')
