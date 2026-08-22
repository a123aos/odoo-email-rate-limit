# Odoo Email Rate Limit & Customer Sender Pools

Odoo 19 module for persistent customer-based sender pools.

## Behavior

### New signup customer

Uninvited B2C signup customers are assigned round-robin:

- Customer A -> `signup1`
- Customer B -> `signup2`
- Customer C -> `signup1`

The assignment is stored on `res.partner.email_sender_pool` and does not change later. Therefore the same customer keeps the same sender for later sales orders, invoices, delivery orders, and other customer emails.

### Existing customer entering an order flow

Customers without a sender assignment receive the order pool on their first sales/order-flow email:

- Customer C -> `order1`
- Customer D -> `order2`
- Customer E -> `order1`

The order pool is only allocated from `sale.order`, outgoing `stock.picking`, and customer-facing `account.move` flows (`out_invoice`, `out_refund`, `out_receipt`).

## Settings

Configure four sender addresses and optional outgoing mail servers in Settings:

- Signup 1 / Signup 2
- Order 1 / Order 2

The configured `mail_server_id` is written to `mail.mail` together with `email_from`, so Odoo's normal queue and SMTP grouping can continue to operate.

## Concurrency

Pool allocation uses PostgreSQL transaction advisory locks so concurrent Odoo workers do not allocate the same sender in the same pool.

## Customer field

System administrators can see `Email Sender Pool` on the customer form to inspect or manually correct an assignment.
