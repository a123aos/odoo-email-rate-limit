from odoo import api, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _signup_create_user(self, values):
        # An uninvited signup creates a new customer. Assign the signup pool
        # before the signup confirmation email is generated/sent.
        is_new_external_signup = not values.get('partner_id')
        user = super()._signup_create_user(values)
        partner = user.partner_id
        if is_new_external_signup and partner and not partner.email_sender_pool:
            partner.email_sender_pool = self.env['mail.mail']._allocate_sender_pool('signup')
        return user
