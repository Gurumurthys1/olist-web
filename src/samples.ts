// Real customers, products and sellers from the Olist data (they exist in Redshift),
// so a new order made in the form or the template passes the validator's checks.
export const CUSTOMERS = [
  { id: '06b8999e2fba1a1fbc88172c00ba8bc7', label: 'Franca, SP' },
  { id: '5aa9e4fdd4dfd20959cad2d772509598', label: 'Rio de Janeiro, RJ' },
  { id: '5e274e7a0c3809e14aba7ad5aae0d407', label: 'Timoteo, MG' },
  { id: '5adf08e34b2e993982a47070956c5c65', label: 'Curitiba, PR' },
  { id: '879864dab9bc3047522c92c82e1212b8', label: 'Jaragua do Sul, SC' },
  { id: '1f1c7bf1c9b041b292af6c1c4470b753', label: 'Caxias do Sul, RS' },
  { id: '2d5831cb2dff7cdefba62e950ae3dc7b', label: 'Camacari, BA' },
  { id: 'a905baa530258422594f1b05615bd225', label: 'Fortaleza, CE' },
  { id: '4fa19f7da692e6bf9602aaad3c372eda', label: 'Brasilia, DF' },
  { id: 'b80adce6a72fc096b80a540312a24a95', label: 'Paulista, PE' },
]

export const PRODUCTS = [
  { id: 'e3e020af31d4d89d2602272b315c3f6e', label: 'health_beauty' },
  { id: '3e9b58f1436820c248d3f98d7229bb14', label: 'watches_gifts' },
  { id: '14aa47b7fe5c25522b47b4b29c98dcb9', label: 'bed_bath_table' },
  { id: '96bd76ec8810374ed1b65e291975717f', label: 'sports_leisure' },
  { id: 'a1b71017a84f92fd8da4aeefba108a24', label: 'computers_accessories' },
  { id: '2548af3e6e77a690cf3eb6368e9ab61e', label: 'furniture_decor' },
  { id: '9dc1a7de274444849c219cff195d0b71', label: 'housewares' },
  { id: '8c92109888e8cdf9d66dc7e463025574', label: 'toys' },
  { id: '92bf5d2084dfbcb57d9db7838bac5cd0', label: 'telephony' },
  { id: '1e9e8ef04dbcff4541ed26657ea517e5', label: 'perfumery' },
]

export const SELLERS = [
  { id: '3442f8959a84dea7ee197c632cb2df15', label: 'Campinas, SP' },
  { id: 'ce3ad9de960102d0677a81f5d0bb7b2d', label: 'Rio de Janeiro, RJ' },
  { id: '2a1348e9addc1af5aaa619b1a3679d6b', label: 'Belo Horizonte, MG' },
  { id: 'ccc4bbb5f32a6ab2b7066a4130f114e3', label: 'Curitiba, PR' },
  { id: '7b8e8ec35bad4b0ef7e3963650b0a87b', label: 'Tubarao, SC' },
  { id: '8bd0e3abda539b9479c4b44a691be1ec', label: 'Tres de Maio, RS' },
]

export const PAYMENT_TYPES = ['credit_card', 'boleto', 'debit_card', 'voucher']
export const STATUSES = ['delivered', 'shipped', 'processing', 'approved', 'canceled']

export const CSV_COLUMNS = [
  'order_id', 'customer_id', 'order_status', 'order_purchase_timestamp',
  'order_estimated_delivery_date', 'order_delivered_customer_date',
  'product_id', 'seller_id', 'price', 'freight_value', 'payment_type', 'payment_installments',
]

/** A new order id in the Olist format: 32 random hex characters. */
export function newOrderId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

export function toCsv(rows: Record<string, string>[]) {
  const cell = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v)
  return [CSV_COLUMNS.join(','), ...rows.map((r) => CSV_COLUMNS.map((c) => cell(r[c] ?? '')).join(','))].join('\n') + '\n'
}

/** Template: two orders (the first has two items), with fresh order ids. */
export function templateCsv() {
  const a = newOrderId()
  const b = newOrderId()
  const base = {
    order_status: 'delivered', order_purchase_timestamp: '2018-10-25 14:30:00',
    order_estimated_delivery_date: '2018-11-10', order_delivered_customer_date: '2018-11-02',
    payment_type: 'credit_card', payment_installments: '3',
  }
  return toCsv([
    { ...base, order_id: a, customer_id: CUSTOMERS[0].id, product_id: PRODUCTS[0].id, seller_id: SELLERS[0].id, price: '129.90', freight_value: '15.50' },
    { ...base, order_id: a, customer_id: CUSTOMERS[0].id, product_id: PRODUCTS[1].id, seller_id: SELLERS[0].id, price: '89.00', freight_value: '12.00' },
    { ...base, order_id: b, customer_id: CUSTOMERS[1].id, product_id: PRODUCTS[2].id, seller_id: SELLERS[1].id, price: '249.00', freight_value: '22.30', payment_type: 'boleto', payment_installments: '1' },
  ])
}
