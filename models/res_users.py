from datetime import datetime, timezone

from odoo import api, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _signup_create_user(self, values):
        is_new_external_signup = not values.get('partner_id')
        user = super()._signup_create_user(values)
        partner = user.partner_id
        if is_new_external_signup and partner:
            server = self.env['mail.mail']._allocate_sender_pool('signup')
            partner.sudo().write({
                'email_sender_server_id': server.id,
                'email_sender_pool_date': datetime.now(timezone.utc).date(),
            })
        return user
