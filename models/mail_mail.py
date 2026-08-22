import hashlib
import logging
from datetime import datetime, timezone

from odoo import api, models

_logger = logging.getLogger(__name__)


class MailMail(models.Model):
    _inherit = 'mail.mail'

    @api.model
    def _utc_date(self):
        return datetime.now(timezone.utc).date()

    @api.model
    def _allocate_sender_pool(self, pool_type):
        """Return the next server in the requested pool, using UTC-day round robin."""
        if pool_type not in ('signup', 'order'):
            raise ValueError('Unknown sender pool type: %s' % pool_type)
        servers = self.env['ir.mail_server'].sudo().search(
            [('sender_pool', '=', pool_type), ('active', '=', True)], order='sequence,id'
        )
        if not servers:
            raise ValueError('No active outgoing mail server is configured for the %s pool.' % pool_type)

        icp = self.env['ir.config_parameter'].sudo()
        lock_key = int.from_bytes(
            hashlib.sha256(('odoo_email_sender_pool:%s' % pool_type).encode()).digest()[:8],
            byteorder='big', signed=False,
        ) - (1 << 63)
        self.env.cr.execute('SELECT pg_advisory_xact_lock(%s)', [lock_key])

        date_key = 'odoo_email_rate_limit.%s_counter_date' % pool_type
        counter_key = 'odoo_email_rate_limit.%s_next' % pool_type
        today = self._utc_date().isoformat()
        if icp.get_param(date_key) != today:
            icp.set_param(date_key, today)
            icp.set_param(counter_key, '1')

        current = int(icp.get_param(counter_key, '1') or '1')
        server = servers[(current - 1) % len(servers)]
        icp.set_param(counter_key, str(current + 1))
        return server

    @api.model
    def _get_customer_partner(self, values):
        recipient_ids = values.get('recipient_ids') or []
        if recipient_ids:
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
    def _is_order_flow_mail(self, values):
        model = values.get('model')
        if model == 'sale.order':
            return True
        if model == 'stock.picking':
            record = self.env[model].browse(values.get('res_id')).exists()
            return bool(record and record.picking_type_code == 'outgoing')
        if model == 'account.move':
            record = self.env[model].browse(values.get('res_id')).exists()
            return bool(record and record.move_type in ('out_invoice', 'out_refund', 'out_receipt'))
        return False

    @api.model
    def _apply_customer_sender_pool(self, values):
        partner = self._get_customer_partner(values)
        if not partner:
            return values

        today = self._utc_date()
        pool = partner.email_sender_pool if partner.email_sender_pool_date == today else False
        if not pool:
            if not self._is_order_flow_mail(values):
                return values
            pool = self._allocate_sender_pool('order')
            partner.sudo().write({
                'email_sender_pool': pool,
                'email_sender_pool_date': today,
            })

        server = self.env['ir.mail_server'].sudo().search([
            ('sender_pool', '=', 'signup' if pool == 'signup' else 'order'),
            ('active', '=', True),
        ], order='sequence,id', limit=1)
        # The actual assigned server is stored separately below when a signup
        # or order allocation occurs. Pool names on the partner identify the
        # customer-day assignment; mail_mail creation must use the server
        # selected for that assignment.
        if server and not values.get('mail_server_id'):
            # Deterministic customer-day server selection from partner id,
            # while preserving the pool-level assignment across all emails.
            servers = self.env['ir.mail_server'].sudo().search([
                ('sender_pool', '=', 'signup' if pool == 'signup' else 'order'),
                ('active', '=', True),
            ], order='sequence,id')
            if servers:
                values['mail_server_id'] = servers[(partner.id - 1) % len(servers)].id
                values['email_from'] = servers[(partner.id - 1) % len(servers)].smtp_user or values.get('email_from')
        return values

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            try:
                self._apply_customer_sender_pool(values)
            except Exception:
                _logger.exception('Unable to apply customer email sender pool')
        return super().create(vals_list)
