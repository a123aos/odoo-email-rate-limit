# Odoo Email Rate Limit

Odoo 19 module for shared outgoing-mail-server rate limiting, a dedicated instant-email queue, and optional SMTP fallback.

## Design

- Odoo's native `mail.mail` queue remains the mass/background queue.
- Template `Send Instantly` is converted into `email.rate.queue`.
- Both queues share the same rate limit on the selected `ir.mail_server`.
- When a server reaches its per-minute quota, additional mail stays outgoing and is scheduled for the next minute window.
- Manual **Send** from the Odoo Emails screen bypasses the background limiter.
- Actual SMTP rate-limit responses can be retried and optionally moved to a configured fallback server.
- The fallback server has its own independent quota.
- PostgreSQL row locking on the outgoing server keeps the quota shared across Odoo workers.

## Important

Install and test in a non-production database first. In particular, verify the exact SMTP error text returned by Lark and exercise both the primary and fallback servers before enabling this for customer email.
