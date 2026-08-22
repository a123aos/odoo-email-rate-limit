from odoo import models


class EmailSenderPoolState:
    """Round-robin state helper.

    This is intentionally a plain Python helper, not an Odoo model. Keeping the
    pool cursor in ir.config_parameter avoids registering an extra model during
    registry construction and therefore keeps the addon compatible with the
    Odoo 19 registry loader.
    """

    def __init__(self, env):
        self.env = env

    def select_server(self, pool, servers):
        selected = self.select_servers(pool, servers, 1)
        return selected[0] if selected else self.env["ir.mail_server"].browse()

    def select_servers(self, pool, servers, count):
        if not servers or count <= 0:
            return []

        # Serialize updates for each pool inside the current PostgreSQL
        # transaction. pg_advisory_xact_lock is released automatically when the
        # transaction ends.
        lock_key = 0x41524954525A + (1 if pool == "signup" else 2)
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))

        ICP = self.env["ir.config_parameter"].sudo()
        key = f"odoo_email_rate_limit.sender_pool.{pool}.next_index"
        try:
            index = int(ICP.get_param(key, "0")) % len(servers)
        except (TypeError, ValueError):
            index = 0

        selected = [servers[(index + offset) % len(servers)] for offset in range(count)]
        ICP.set_param(key, str((index + count) % len(servers)))
        return selected
