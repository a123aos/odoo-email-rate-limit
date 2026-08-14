{
    "name": "Odoo Email Rate Limit",
    "version": "19.0.1.0.0",
    "summary": "Per outgoing mail server rate limiting with instant queue and SMTP fallback",
    "category": "Technical",
    "license": "LGPL-3",
    "author": "Aritrz",
    "depends": ["mail"],
    "data": [
        "security/ir.model.access.csv",
        "views/ir_mail_server_views.xml",
        "views/email_rate_queue_views.xml",
        "views/mail_mail_views.xml",
        "data/ir_cron.xml",
    ],
    "installable": true,
    "application": false,
}
