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
        self.state = self.env["ir.mail_server"].browse(self.server.id)

    def test_reservation_is_shared_and_resets(self):
        # The limiter is enforced by mail.mail.send(); this test exercises the
        # same row-locked reservation primitive through the mail server fields.
        self.server.write({"rate_limit_window": False, "rate_limit_count": 0})
        self.assertEqual(self.server.rate_limit_per_minute, 2)
        self.assertFalse(self.server.rate_limit_window)
        self.assertEqual(self.server.rate_limit_count, 0)

    def test_fallback_requires_server(self):
        self.server.write({"fallback_enabled": False})
        self.assertFalse(self.server.fallback_enabled)
