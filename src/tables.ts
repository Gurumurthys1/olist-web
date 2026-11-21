// The 9 Olist tables the website can add rows to. Same columns and rules as the
// upload validator Lambda (backend/upload_validator), which does the real checking.
import { CUSTOMERS, ORDERS, PRODUCTS, SELLERS } from './samples'

export type Kind = 'id' | 'text' | 'int' | 'num' | 'ts' | 'zip' | 'state' | 'enum' | 'category'
export type Column = {
  name: string
  kind: Kind
  required?: boolean
  key?: boolean            // part of the row's identity; a new id can be generated
  ref?: string             // must already exist: customer / product / seller / order / category
  values?: string[]        // allowed values (enum)
  example: string
}
export type TableSpec = { name: string; label: string; about: string; makes?: string; columns: Column[] }

export const STATUSES = ['created', 'approved', 'invoiced', 'processing', 'shipped', 'delivered', 'canceled', 'unavailable']
export const PAYMENT_TYPES = ['credit_card', 'boleto', 'voucher', 'debit_card', 'not_defined']
export const STATES = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT', 'PA',
  'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO']

const c = (name: string, kind: Kind, example: string, extra: Partial<Column> = {}): Column =>
  ({ name, kind, example, ...extra })

export const TABLES: TableSpec[] = [
  {
    name: 'orders', label: 'Orders', makes: 'order',
    about: 'One row per order. The customer must exist (or be uploaded first).',
    columns: [
      c('order_id', 'id', '', { required: true, key: true }),
      c('customer_id', 'id', CUSTOMERS[0].id, { required: true, ref: 'customer' }),
      c('order_status', 'enum', 'delivered', { required: true, values: STATUSES }),
      c('order_purchase_timestamp', 'ts', '2018-10-25 14:30:00', { required: true }),
      c('order_approved_at', 'ts', '2018-10-25 15:00:00'),
      c('order_delivered_carrier_date', 'ts', '2018-10-26 10:00:00'),
      c('order_delivered_customer_date', 'ts', '2018-11-02 16:00:00'),
      c('order_estimated_delivery_date', 'ts', '2018-11-10 00:00:00'),
    ],
  },
  {
    name: 'order_items', label: 'Order items',
    about: 'One row per product in an order. The order, product and seller must exist.',
    columns: [
      c('order_id', 'id', ORDERS[0].id, { required: true, key: true, ref: 'order' }),
      c('order_item_id', 'int', '2', { required: true, key: true }),
      c('product_id', 'id', PRODUCTS[0].id, { required: true, ref: 'product' }),
      c('seller_id', 'id', SELLERS[0].id, { required: true, ref: 'seller' }),
      c('shipping_limit_date', 'ts', '2017-10-06 11:07:15'),
      c('price', 'num', '129.90', { required: true }),
      c('freight_value', 'num', '15.50', { required: true }),
    ],
  },
  {
    name: 'payments', label: 'Payments',
    about: 'One row per payment of an order. The order must exist.',
    columns: [
      c('order_id', 'id', ORDERS[0].id, { required: true, key: true, ref: 'order' }),
      c('payment_sequential', 'int', '2', { required: true, key: true }),
      c('payment_type', 'enum', 'credit_card', { required: true, values: PAYMENT_TYPES }),
      c('payment_installments', 'int', '3', { required: true }),
      c('payment_value', 'num', '145.40', { required: true }),
    ],
  },
  {
    name: 'reviews', label: 'Reviews',
    about: 'Customer reviews (score 1 to 5). The order must exist.',
    columns: [
      c('review_id', 'id', '', { required: true, key: true }),
      c('order_id', 'id', ORDERS[0].id, { required: true, key: true, ref: 'order' }),
      c('review_score', 'int', '5', { required: true }),
      c('review_comment_title', 'text', 'otimo'),
      c('review_comment_message', 'text', 'chegou antes do prazo'),
      c('review_creation_date', 'ts', '2017-10-11 00:00:00', { required: true }),
      c('review_answer_timestamp', 'ts', '2017-10-12 10:00:00'),
    ],
  },
  {
    name: 'customers', label: 'Customers', makes: 'customer',
    about: 'New customers. Upload them before their orders.',
    columns: [
      c('customer_id', 'id', '', { required: true, key: true }),
      c('customer_unique_id', 'id', '', { required: true }),
      c('customer_zip_code_prefix', 'zip', '01310', { required: true }),
      c('customer_city', 'text', 'sao paulo', { required: true }),
      c('customer_state', 'state', 'SP', { required: true }),
    ],
  },
  {
    name: 'sellers', label: 'Sellers', makes: 'seller',
    about: 'New sellers. Upload them before order items that use them.',
    columns: [
      c('seller_id', 'id', '', { required: true, key: true }),
      c('seller_zip_code_prefix', 'zip', '13010', { required: true }),
      c('seller_city', 'text', 'campinas', { required: true }),
      c('seller_state', 'state', 'SP', { required: true }),
    ],
  },
  {
    name: 'products', label: 'Products', makes: 'product',
    about: 'New products. The category (Portuguese name) must exist.',
    columns: [
      c('product_id', 'id', '', { required: true, key: true }),
      c('product_category_name', 'category', 'perfumaria', { required: true, ref: 'category' }),
      c('product_name_lenght', 'int', '40'),
      c('product_description_lenght', 'int', '300'),
      c('product_photos_qty', 'int', '2'),
      c('product_weight_g', 'int', '500'),
      c('product_length_cm', 'int', '20'),
      c('product_height_cm', 'int', '10'),
      c('product_width_cm', 'int', '15'),
    ],
  },
  {
    name: 'category_translation', label: 'Category names', makes: 'category',
    about: 'Portuguese category name and its English name.',
    columns: [
      c('product_category_name', 'category', 'jogos_de_tabuleiro', { required: true, key: true }),
      c('product_category_name_english', 'category', 'board_games', { required: true }),
    ],
  },
  {
    name: 'geolocation', label: 'Geolocation',
    about: 'GPS points per zip code (inside Brazil).',
    columns: [
      c('geolocation_zip_code_prefix', 'zip', '01310', { required: true }),
      c('geolocation_lat', 'num', '-23.5614', { required: true }),
      c('geolocation_lng', 'num', '-46.6559', { required: true }),
      c('geolocation_city', 'text', 'sao paulo', { required: true }),
      c('geolocation_state', 'state', 'SP', { required: true }),
    ],
  },
]
