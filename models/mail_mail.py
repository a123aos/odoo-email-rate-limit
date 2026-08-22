import hashlib
from datetime import datetime, timezone

from odoo import api, fields, models


class MailMail(models.Model):
    _inherit = 'mail.mail'

    sender_pool = fields.Selection([
        ('signup', 'Signup Pool'),
        ('order', 'Order Pool'),
    ], string='Sender Pool', copy=False, index=True,
       help='Sender pool selected by the originating email template.')

    @api.model
    def _utc_date(self):
        return datetime.now(timezone.utc).date()

    @api.model
    def _allocate_sender_pool(self, pool_type):
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

        recipient_ids = values.get('recipient_ids') or []
        ids = []
        for command in recipient_ids:
            if isinstance(command, (list, tuple)) and command:
                if command[0] == 6 and len(command) >= 3:
                    ids.extend(command[2] or [])
                elif command[0] == 4 and len(command) >= 2:
                    ids.append(command[1])
        if ids:
            partners = self.env['res.partner'].browse(ids).exists().filtered('email')
            if partners:
                return partners.sorted('id')[0]
        return self.env['res.partner']

    @api.model
    def _apply_customer_sender_pool(self, values):
        pool_type = values.get('sender_pool')
        if not pool_type:
            return values

        partner = self._get_customer_partner(values)
        if not partner:
            return values

        today = self._utc_date()
        server = self.env['ir.mail_server']
        if partner.email_sender_pool_date == today and partner.email_sender_server_id:
            server = partner.email_sender_server_id
        else:
            server = self._allocate_sender_pool(pool_type)
            partner.sudo().write({
                'email_sender_server_id': server.id,
                'email_sender_pool_date': today,
            })

        values['mail_server_id'] = server.id
        if server.smtp_user:
            values['email_from'] = server.smtp_user
        return values

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            self._apply_customer_sender_pool(values)
        return super().create(vals_list)
