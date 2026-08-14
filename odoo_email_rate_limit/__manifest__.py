{
    "name": "Email Rate Limit",
    "version": "19.0.1.0.0",
    "category": "Discuss/Email",
    "summary": "Rate-limit outgoing email with instant queue and fallback",
    "depends": ["mail"],
    "data": [
        "security/ir.model.access.csv",
        "views/ir_mail_server_views.xml",
        "views/email_queue_views.xml",
        "data/ir_cron.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
