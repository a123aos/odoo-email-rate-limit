from odoo import models


class EmailSenderPoolState:
    """Per-customer sender-pool allocation helper.

    The cursor is advanced once for each new customer allocation, never for
    each email. A dedicated ir.sequence is used per pool so the round-robin
    position is persisted independently of the mail record being created.
    """

    def __init__(self, env):
        self.env = env

    def _sequence_code(self, pool):
        return f"odoo_email_rate_limit.sender_pool.{pool}"

    def _get_or_create_sequence(self, pool, size):
        Sequence = self.env["ir.sequence"].sudo()
        code = self._sequence_code(pool)
        sequence = Sequence.search([("code", "=", code)], limit=1)
        if not sequence:
            sequence = Sequence.create({
                "name": f"Email Sender Pool: {pool}",
                "code": code,
                "implementation": "standard",
                "prefix": "",
                "padding": 1,
                "number_increment": 1,
                "number_next": 1,
            })
        return sequence

    def select_server(self, pool, servers):
        selected = self.select_servers(pool, servers, 1)
        return selected[0] if selected else self.env["ir.mail_server"].browse()

    def select_servers(self, pool, servers, count):
        if not servers or count <= 0:
            return []

        # One sequence number is consumed per customer allocation. The caller
        # groups emails by customer, so count here is the number of distinct
        # customers, not the number of emails.
        sequence = self._get_or_create_sequence(pool, len(servers))
        selected = []
        for _index in range(count):
            number = sequence.next_by_id()
            position = (int(number) - 1) % len(servers)
            selected.append(servers[position])
        return selected
