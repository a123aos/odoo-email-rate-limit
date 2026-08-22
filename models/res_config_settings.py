from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    signup1_email = fields.Char(
        string='Signup 1 From',
        config_parameter='odoo_email_rate_limit.signup1_email',
    )
    signup1_mail_server_id = fields.Many2one(
        'ir.mail_server',
        string='Signup 1 Mail Server',
        config_parameter='odoo_email_rate_limit.signup1_mail_server_id',
    )
    signup2_email = fields.Char(
        string='Signup 2 From',
        config_parameter='odoo_email_rate_limit.signup2_email',
    )
    signup2_mail_server_id = fields.Many2one(
        'ir.mail_server',
        string='Signup 2 Mail Server',
        config_parameter='odoo_email_rate_limit.signup2_mail_server_id',
    )

    order1_email = fields.Char(
        string='Order 1 From',
        config_parameter='odoo_email_rate_limit.order1_email',
    )
    order1_mail_server_id = fields.Many2one(
        'ir.mail_server',
        string='Order 1 Mail Server',
        config_parameter='odoo_email_rate_limit.order1_mail_server_id',
    )
    order2_email = fields.Char(
        string='Order 2 From',
        config_parameter='odoo_email_rate_limit.order2_email',
    )
    order2_mail_server_id = fields.Many2one(
        'ir.mail_server',
        string='Order 2 Mail Server',
        config_parameter='odoo_email_rate_limit.order2_mail_server_id',
    )
