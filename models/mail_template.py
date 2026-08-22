from odoo import fields, models


class MailTemplate(models.Model):
    _inherit = 'mail.template'

    sender_pool_mode = fields.Selection([
        ('server', 'Fixed Outgoing Server'),
        ('pool', 'Sender Pool'),
    ], string='Sender Selection', default='server', required=True,
       help='Choose a fixed outgoing server or let the customer sender pool select one.')
    sender_pool = fields.Selection([
        ('signup', 'Signup Pool'),
        ('order', 'Order Pool'),
    ], string='Sender Pool',
       help='Pool used when Sender Selection is Sender Pool.')
