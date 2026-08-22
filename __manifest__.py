{
    'name': 'Email Rate Limit & Customer Sender Pools',
    'version': '19.0.4.0.0',
    'category': 'Technical/Email',
    'summary': 'Daily customer sender pools for outgoing email',
    'depends': ['mail', 'auth_signup'],
    'data': [
        'views/res_config_settings_views.xml',
        'views/res_partner_views.xml',
        'views/ir_mail_server_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
