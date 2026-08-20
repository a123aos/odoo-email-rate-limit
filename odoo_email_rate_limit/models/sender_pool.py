from odoo import api, fields, models


class EmailSenderPoolState(models.Model):
    _name = "email.sender.pool.state"
    _description = "Email Sender Pool Round Robin State"

    pool = fields.Selection([("signup", "Signup"), ("order", "Order")], required=True, index=True)
    next_index = fields.Integer(default=0)

    _sql_constraints = [("pool_unique", "unique(pool)", "There must be one round-robin state per sender pool.")]

    @api.model
    def select_server(self, pool, servers):
        if not servers:
            return self.env["ir.mail_server"].browse()
        self.env.cr.execute(
            f"INSERT INTO {self._table} (pool, next_index, create_uid, create_date, write_uid, write_date) VALUES (%s,0,%s,NOW(),%s,NOW()) ON CONFLICT (pool) DO NOTHING",
            (pool, self.env.uid, self.env.uid),
        )
        self.env.cr.execute(f"SELECT id,next_index FROM {self._table} WHERE pool=%s FOR UPDATE", (pool,))
        row = self.env.cr.fetchone()
        index = (row[1] if row else 0) % len(servers)
        server = servers[index]
        self.env.cr.execute(
            f"UPDATE {self._table} SET next_index=%s,write_uid=%s,write_date=NOW() WHERE id=%s",
            ((index + 1) % len(servers), self.env.uid, row[0]),
        )
        return server
