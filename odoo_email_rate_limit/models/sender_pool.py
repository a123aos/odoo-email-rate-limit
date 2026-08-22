from odoo import models


class EmailSenderPoolState:
    """Per-customer sender-pool allocation helper.

    A customer consumes exactly one slot when first assigned a pool sender for
    the day. Subsequent emails for that customer reuse the stored affinity and
    do not advance the pool. The allocation cursor is persisted in the database
    and protected by a transaction advisory lock so concurrent workers cannot
    assign the same slot to two different customers.
    """

    def __init__(self, env):
        self.env = env

    def select_server(self, pool, servers):
        selected = self.select_servers(pool, servers, 1)
        return selected[0] if selected else self.env["ir.mail_server"].browse()

    def select_servers(self, pool, servers, count):
        if not servers or count <= 0:
            return []

        lock_key = 0x41524954525A + (1 if pool == "signup" else 2)
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))

        ICP = self.env["ir.config_parameter"].sudo()
        key = f"odoo_email_rate_limit.sender_pool.{pool}.next_index"

        # Read the cursor directly from SQL so another Odoo worker cannot give
        # us a stale ir.config_parameter cache value.
        self.env.cr.execute(
            "SELECT value FROM ir_config_parameter WHERE key = %s FOR UPDATE",
            (key,),
        )
        row = self.env.cr.fetchone()
        try:
            index = int(row[0]) % len(servers) if row and row[0] is not None else 0
        except (TypeError, ValueError):
            index = 0

        selected = [servers[(index + offset) % len(servers)] for offset in range(count)]
        next_index = (index + count) % len(servers)

        if row:
            self.env.cr.execute(
                "UPDATE ir_config_parameter SET value = %s WHERE key = %s",
                (str(next_index), key),
            )
        else:
            self.env.cr.execute(
                "INSERT INTO ir_config_parameter (key, value, create_uid, write_uid, create_date, write_date) "
                "VALUES (%s, %s, %s, %s, NOW(), NOW())",
                (key, str(next_index), self.env.uid, self.env.uid),
            )

        ICP.invalidate_cache()
        return selected
