from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase


class TestEmailRateLimit(TransactionCase):
    def setUp(self):
        super().setUp()
        self.server = self.env["ir.mail_server"].create({
            "name": "Rate Limit Test",
            "smtp_host": "127.0.0.1",
            "smtp_port": 2525,
            "rate_limit_enabled": True,
            "rate_limit_per_minute": 2,
        })

    def _mail(self, subject):
        message = self.env["mail.message"].create({
            "message_type": "email_outgoing",
            "subject": subject,
            "body": "Test",
            "email_from": "sender@example.com",
            "email_to": "recipient@example.com",
        })
        return self.env["mail.mail"].create({
            "mail_message_id": message.id,
            "mail_server_id": self.server.id,
            "email_from": "sender@example.com",
            "email_to": "recipient@example.com",
        })

    def test_shared_quota_defers_overflow_to_next_minute(self):
        mails = self.env["mail.mail"]
        for subject in ("One", "Two", "Three"):
            mails |= self._mail(subject)

        allowed = mails._rate_limit_prepare_batch(self.server, mails.ids)

        self.assertEqual(len(allowed), 2)
        self.assertEqual(self.server.rate_limit_count, 2)
        third = mails.sorted(lambda mail: mail.id)[-1]
        self.assertEqual(
            third.scheduled_date,
            self.server.rate_limit_window + timedelta(minutes=1),
        )

    def test_new_window_resets_counter(self):
        now = datetime.utcnow().replace(second=0, microsecond=0)
        self.server.write({
            "rate_limit_window": now - timedelta(minutes=1),
            "rate_limit_count": 2,
        })
        mail = self._mail("Reset")
        allowed = mail._rate_limit_prepare_batch(self.server, mail.ids)
        self.assertEqual(allowed, mail)
        self.assertEqual(self.server.rate_limit_count, 1)
        self.assertEqual(self.server.rate_limit_window, now)

    def test_fallback_configuration_requires_server(self):
        with self.assertRaises(Exception):
            self.server.write({"fallback_enabled": True})

    def test_manual_send_context_bypasses_limiter(self):
        mail = self._mail("Manual")
        self.assertTrue(mail.with_context(rate_limit_bypass=True)._rate_limit_is_exempt())
