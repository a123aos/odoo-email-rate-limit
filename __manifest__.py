{
    'name': 'Email Rate Limit & Customer Sender Pools',
    'version': '19.0.3.0.0',
    'category': 'Technical/Email',
    'summary': 'Persistent customer-based sender pools for outgoing email',
    'depends': ['mail', 'auth_signup'],
    'data': [
        'views/res_config_settings_views.xml',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
