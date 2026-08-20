{
    "name": "Email Rate Limit",
    "version": "19.0.2.0.0",
    "category": "Discuss/Email",
    "summary": "Lark-compatible email rate limits, sender pools and delayed queue",
    "depends": ["mail"],
    "data": [
        "security/ir.model.access.csv",
        "views/ir_mail_server_views.xml",
        "views/email_queue_views.xml",
        "data/ir_cron.xml",
    ],
    "installable": true,
    "application": false,
    "license": "LGPL-3",
}
