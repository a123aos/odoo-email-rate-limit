{
    "name": "Email Rate Limit",
    "version": "19.0.2.1.3",
    "category": "Discuss/Email",
    "summary": "Lark-compatible email rate limits, sender pools and delayed queue",
    "depends": ["mail"],
    "data": [
        "security/ir.model.access.csv",
        "views/ir_mail_server_views.xml",
        "views/email_queue_views.xml",
        "views/rate_limit_dashboard_action.xml",
        "views/mail_template_views.xml",
        "data/ir_cron.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "odoo_email_rate_limit/static/src/js/rate_limit_dashboard.js",
            "odoo_email_rate_limit/static/src/xml/rate_limit_dashboard.xml",
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
