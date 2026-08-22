from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MailTemplate(models.Model):
    _inherit = 'mail.template'

    sender_pool_mode = fields.Selection([
        ('server', 'Fixed Outgoing Server'),
        ('pool', 'Sender Pool'),
    ], string='Sender Selection', default='server', required=True,
       help='Use a fixed outgoing server or select a customer sender pool.')
    sender_pool = fields.Selection([
        ('signup', 'Signup Pool'),
        ('order', 'Order Pool'),
    ], string='Sender Pool',
       help='Pool used when Sender Selection is Sender Pool.')

    @api.onchange('sender_pool_mode')
    def _onchange_sender_pool_mode(self):
        if self.sender_pool_mode == 'pool':
            self.mail_server_id = False
        else:
            self.sender_pool = False

    @api.constrains('sender_pool_mode', 'sender_pool')
    def _check_sender_pool(self):
        for template in self:
            if template.sender_pool_mode == 'pool' and not template.sender_pool:
                raise ValidationError('Please select a Sender Pool when Sender Selection is Sender Pool.')

    def generate_email(self, res_ids, fields=None):
        results = super().generate_email(res_ids, fields=fields)
        if self.sender_pool_mode != 'pool':
            return results

        def add_pool(values):
            if isinstance(values, dict):
                values['sender_pool'] = self.sender_pool
                values['mail_server_id'] = False

        if isinstance(results, dict) and results and all(isinstance(v, dict) for v in results.values()):
            for values in results.values():
                add_pool(values)
        elif isinstance(results, dict):
            add_pool(results)
        return results
