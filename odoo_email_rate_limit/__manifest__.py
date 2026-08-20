{
    "name": "Email Rate Limit",
    "version": "19.0.2.1.0",
    "category": "Discuss/Email",
    "summary": "Lark-compatible email rate limits, sender pools and delayed queue",
    "depends": ["mail"],
    "data": [
        "security/ir.model.access.csv",
        "views/ir_mail_server_views.xml",
        "views/email_queue_views.xml",
        "views/rate_limit_dashboard_views.xml",
        "data/ir_cron.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
