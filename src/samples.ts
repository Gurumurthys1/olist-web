// Real ids from the Olist data (they exist in Redshift). The form offers them as suggestions,
// so a new row that points to a customer / product / seller / order passes the validator.
export type Option = { id: string; label: string }

export const CUSTOMERS: Option[] = [
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

export const PRODUCTS: Option[] = [
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

export const SELLERS: Option[] = [
  { id: '3442f8959a84dea7ee197c632cb2df15', label: 'Campinas, SP' },
  { id: 'ce3ad9de960102d0677a81f5d0bb7b2d', label: 'Rio de Janeiro, RJ' },
  { id: '2a1348e9addc1af5aaa619b1a3679d6b', label: 'Belo Horizonte, MG' },
  { id: 'ccc4bbb5f32a6ab2b7066a4130f114e3', label: 'Curitiba, PR' },
  { id: '7b8e8ec35bad4b0ef7e3963650b0a87b', label: 'Tubarao, SC' },
  { id: '8bd0e3abda539b9479c4b44a691be1ec', label: 'Tres de Maio, RS' },
]

export const ORDERS: Option[] = [
  { id: 'e481f51cbdc54678b7cc49136f2d6af7', label: 'order from 2017-10-02 (history)' },
]

export const CATEGORIES: Option[] = [
  'perfumaria', 'beleza_saude', 'esporte_lazer', 'informatica_acessorios', 'moveis_decoracao',
  'utilidades_domesticas', 'brinquedos', 'telefonia', 'relogios_presentes', 'cama_mesa_banho',
].map((c) => ({ id: c, label: c }))

export const SUGGESTIONS: Record<string, Option[]> = {
  customer: CUSTOMERS, product: PRODUCTS, seller: SELLERS, order: ORDERS, category: CATEGORIES,
}

/** A new id in the Olist format: 32 random hex characters. */
export function newId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

export function toCsv(columns: string[], rows: Record<string, string>[]) {
  const cell = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v)
  return [columns.join(','), ...rows.map((r) => columns.map((c) => cell(r[c] ?? '')).join(','))].join('\n') + '\n'
}

// ids you created with the form in this browser, offered as suggestions in the next forms
const RECENT_KEY = 'olist-recent-ids'

export function recentIds(kind: string): Option[] {
  try {
    const all = JSON.parse(localStorage.getItem(RECENT_KEY) || '{}') as Record<string, string[]>
    return (all[kind] ?? []).map((id) => ({ id, label: 'added by you' }))
  } catch {
    return []
  }
}

export function rememberId(kind: string, id: string) {
  try {
    const all = JSON.parse(localStorage.getItem(RECENT_KEY) || '{}') as Record<string, string[]>
    all[kind] = [id, ...(all[kind] ?? []).filter((x) => x !== id)].slice(0, 10)
    localStorage.setItem(RECENT_KEY, JSON.stringify(all))
  } catch {
    // storage blocked: suggestions just will not include your own ids
  }
}
