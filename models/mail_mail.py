import hashlib
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class MailMail(models.Model):
    _inherit = 'mail.mail'

    _POOL_CONFIG = {
        'signup1': ('signup1_email', 'signup1_mail_server_id'),
        'signup2': ('signup2_email', 'signup2_mail_server_id'),
        'order1': ('order1_email', 'order1_mail_server_id'),
        'order2': ('order2_email', 'order2_mail_server_id'),
    }

    @api.model
    def _allocate_sender_pool(self, pool_type):
        """Atomically allocate the next sender in a two-address pool.

        PostgreSQL advisory transaction locks prevent two concurrent Odoo
        workers from selecting the same sender.
        """
        if pool_type not in ('signup', 'order'):
            raise ValueError('Unknown sender pool type: %s' % pool_type)

        icp = self.env['ir.config_parameter'].sudo()
        lock_key = int.from_bytes(
            hashlib.sha256(('odoo_email_sender_pool:%s' % pool_type).encode()).digest()[:8],
            byteorder='big', signed=False,
        ) - (1 << 63)
        self.env.cr.execute('SELECT pg_advisory_xact_lock(%s)', [lock_key])

        counter_key = 'odoo_email_rate_limit.%s_next' % pool_type
        current = int(icp.get_param(counter_key, '1') or '1')
        pool = '%s%d' % (pool_type, 1 if current % 2 else 2)
        icp.set_param(counter_key, '2' if current % 2 else '1')
        return pool

    @api.model
    def _get_customer_partner(self, values):
        """Find the business/customer partner this outgoing mail belongs to."""
        recipient_ids = values.get('recipient_ids') or []
        if recipient_ids:
            # Odoo command format: [(6, 0, [ids])] or [(4, id), ...]
            ids = []
            for command in recipient_ids:
                if isinstance(command, (list, tuple)) and command:
                    if command[0] == 6 and len(command) >= 3:
                        ids.extend(command[2] or [])
                    elif command[0] == 4 and len(command) >= 2:
                        ids.append(command[1])
            if ids:
                partners = self.env['res.partner'].browse(ids).exists().sorted('id')
                partners = partners.filtered(lambda p: p.email)
                if partners:
                    return partners[0]

        model = values.get('model')
        res_id = values.get('res_id')
        if model and res_id and model in self.env:
            record = self.env[model].browse(res_id).exists()
            if record:
                if model == 'res.partner':
                    return record if record.email else self.env['res.partner']
                if model == 'res.users' and record.partner_id.email:
                    return record.partner_id
                if 'partner_id' in record._fields:
                    partner = record.partner_id
                    if partner and partner.email:
                        return partner
        return self.env['res.partner']

    @api.model
    def _apply_customer_sender_pool(self, values):
        partner = self._get_customer_partner(values)
        if not partner:
            return values

        # Existing assignment wins forever. A newly purchasing customer gets
        # the order pool once, and all later order/invoice/delivery emails keep
        # using that same sender.
        pool = partner.email_sender_pool
        if not pool:
            pool = self._allocate_sender_pool('order')
            partner.sudo().write({'email_sender_pool': pool})

        email_key, server_key = self._POOL_CONFIG.get(pool, (False, False))
        icp = self.env['ir.config_parameter'].sudo()
        email_from = icp.get_param('odoo_email_rate_limit.%s' % email_key, '') if email_key else ''
        mail_server_id = int(icp.get_param('odoo_email_rate_limit.%s' % server_key, '0') or 0) if server_key else 0

        if email_from:
            values['email_from'] = email_from.strip()
        if mail_server_id:
            server = self.env['ir.mail_server'].sudo().browse(mail_server_id).exists()
            if server:
                values['mail_server_id'] = server.id

        return values

    @api.model_create_multi
    def create(self, vals_list):
        # Routing is done before mail.mail is created so the queue records the
        # final email_from and mail_server_id and Odoo's normal sender grouping
        # can batch messages correctly.
        for values in vals_list:
            try:
                self._apply_customer_sender_pool(values)
            except Exception:
                _logger.exception('Unable to apply customer email sender pool')
        return super().create(vals_list)
