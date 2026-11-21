import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost } from '../api'
import { config } from '../config'
import { useUser } from '../useUser'
import {
  CUSTOMERS, PAYMENT_TYPES, PRODUCTS, SELLERS, STATUSES, newOrderId, templateCsv, toCsv,
} from '../samples'

type UploadRow = {
  upload_id: string; created_at: string; user_email: string; filename: string
  status: string; message: string; errors?: string[]
  row_count?: string; order_count?: string; item_count?: string; total_value?: string
}
type Item = { product_id: string; seller_id: string; price: string; freight_value: string }

const today = () => new Date().toISOString().slice(0, 10)
const plusDays = (d: string, n: number) => {
  const x = new Date(d); x.setDate(x.getDate() + n); return x.toISOString().slice(0, 10)
}

/** Ask the API for a presigned URL, then send the CSV straight to S3. */
async function sendCsv(filename: string, csv: Blob, idToken: string) {
  const { url, upload_id } = await apiPost<{ url: string; upload_id: string }>('/uploads', { filename }, idToken)
  const res = await fetch(url, { method: 'PUT', headers: { 'Content-Type': 'text/csv' }, body: csv })
  if (!res.ok) throw new Error(`S3 upload failed: ${res.status} ${await res.text()}`)
  return upload_id
}

export default function Upload() {
  const { isAdmin, idToken } = useUser()
  const [uploads, setUploads] = useState<UploadRow[]>([])
  const [listError, setListError] = useState('')
  const [msg, setMsg] = useState('')

  const load = useCallback(() => {
    apiGet<{ uploads: UploadRow[] }>('/uploads', idToken)
      .then((r) => { setUploads(r.uploads); setListError('') })
      .catch((e: Error) => setListError(e.message))
  }, [idToken])

  useEffect(() => { if (config.apiUrl) load() }, [load])

  // while a recent file (last 5 minutes) is still being checked, refresh the list every 4 seconds
  const busy = uploads.some((u) => (u.status === 'WAITING_FILE' || u.status === 'VALIDATING')
    && Date.now() - new Date(u.created_at).getTime() < 5 * 60 * 1000)
  useEffect(() => {
    if (!busy) return
    const t = setInterval(load, 4000)
    return () => clearInterval(t)
  }, [busy, load])

  const afterSend = (id: string) => { setMsg(`Sent (upload ${id}). Checking it now…`); setTimeout(load, 1500) }

  if (!isAdmin) {
    return <><h1>Upload data</h1><div className="card notice">Only users in the <b>admin</b> group can upload data.</div></>
  }

  return (
    <>
      <h1>Upload data</h1>
      <p className="muted">
        New orders are checked first. Valid ones are loaded into Redshift by the next pipeline run,
        then they appear on the dashboard and in QuickSight.
      </p>
      {msg && <div className="card notice" style={{ marginBottom: 16 }}>{msg}</div>}

      <section className="grid2">
        <CsvUpload idToken={idToken} onSent={afterSend} />
        <OrderForm idToken={idToken} onSent={afterSend} />
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <div className="row-between">
          <h3>Recent uploads</h3>
          <button className="btn small ghost" onClick={load}>Refresh</button>
        </div>
        {listError && <p className="error">Could not load the list: {listError}</p>}
        {!listError && uploads.length === 0 && <p className="muted">No uploads yet.</p>}
        {uploads.length > 0 && <UploadTable rows={uploads} />}
      </section>
    </>
  )
}

function CsvUpload({ idToken, onSent }: { idToken: string; onSent: (id: string) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const downloadTemplate = () => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([templateCsv()], { type: 'text/csv' }))
    a.download = 'olist_orders_template.csv'
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const send = async () => {
    if (!file) return
    setBusy(true); setError('')
    try {
      onSent(await sendCsv(file.name, file, idToken))
      setFile(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <h3>Upload a CSV file</h3>
      <p className="muted small">One row per item. Rows with the same <code>order_id</code> are one order. Up to 500 rows.</p>
      <button className="btn small ghost" onClick={downloadTemplate}>Download template</button>
      <div className="form-row" style={{ marginTop: 12 }}>
        <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </div>
      <button className="btn" disabled={!file || busy} onClick={send}>{busy ? 'Uploading…' : 'Upload'}</button>
      {error && <p className="error">{error}</p>}
    </div>
  )
}

function OrderForm({ idToken, onSent }: { idToken: string; onSent: (id: string) => void }) {
  const [customer, setCustomer] = useState(CUSTOMERS[0].id)
  const [status, setStatus] = useState('delivered')
  const [purchase, setPurchase] = useState(today())
  const [estimated, setEstimated] = useState(plusDays(today(), 15))
  const [delivered, setDelivered] = useState(today())
  const [payment, setPayment] = useState('credit_card')
  const [installments, setInstallments] = useState('1')
  const [items, setItems] = useState<Item[]>([{ product_id: PRODUCTS[0].id, seller_id: SELLERS[0].id, price: '99.90', freight_value: '15.00' }])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const setItem = (i: number, patch: Partial<Item>) => setItems(items.map((it, j) => (j === i ? { ...it, ...patch } : it)))
  const total = items.reduce((s, it) => s + (Number(it.price) || 0) + (Number(it.freight_value) || 0), 0)

  const send = async () => {
    setBusy(true); setError('')
    try {
      const orderId = newOrderId()
      const rows = items.map((it) => ({
        ...it, order_id: orderId, customer_id: customer, order_status: status,
        order_purchase_timestamp: `${purchase} 12:00:00`, order_estimated_delivery_date: estimated,
        order_delivered_customer_date: status === 'delivered' ? delivered : '',
        payment_type: payment, payment_installments: installments,
      }))
      onSent(await sendCsv(`form_order_${orderId.slice(0, 8)}.csv`, new Blob([toCsv(rows)], { type: 'text/csv' }), idToken))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <h3>Enter one order</h3>
      <div className="form-grid">
        <label>Customer
          <select value={customer} onChange={(e) => setCustomer(e.target.value)}>
            {CUSTOMERS.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
        </label>
        <label>Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <label>Purchase date<input type="date" value={purchase} max={today()} onChange={(e) => setPurchase(e.target.value)} /></label>
        <label>Estimated delivery<input type="date" value={estimated} onChange={(e) => setEstimated(e.target.value)} /></label>
        {status === 'delivered' && (
          <label>Delivered on<input type="date" value={delivered} onChange={(e) => setDelivered(e.target.value)} /></label>
        )}
        <label>Payment
          <select value={payment} onChange={(e) => setPayment(e.target.value)}>
            {PAYMENT_TYPES.map((p) => <option key={p}>{p}</option>)}
          </select>
        </label>
        <label>Installments<input type="number" min={1} max={24} value={installments} onChange={(e) => setInstallments(e.target.value)} /></label>
      </div>

      {items.map((it, i) => (
        <div key={i} className="item-row">
          <select value={it.product_id} onChange={(e) => setItem(i, { product_id: e.target.value })} aria-label="Product">
            {PRODUCTS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
          <select value={it.seller_id} onChange={(e) => setItem(i, { seller_id: e.target.value })} aria-label="Seller">
            {SELLERS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
          <input type="number" min={0.01} step={0.01} value={it.price} onChange={(e) => setItem(i, { price: e.target.value })} aria-label="Price" placeholder="Price" />
          <input type="number" min={0} step={0.01} value={it.freight_value} onChange={(e) => setItem(i, { freight_value: e.target.value })} aria-label="Freight" placeholder="Freight" />
          {items.length > 1 && <button className="btn small ghost" onClick={() => setItems(items.filter((_, j) => j !== i))}>✕</button>}
        </div>
      ))}
      <div className="row-between" style={{ marginTop: 8 }}>
        <button className="btn small ghost" onClick={() => setItems([...items, { ...items[items.length - 1] }])}>+ Add item</button>
        <span className="muted">Total R$ {total.toFixed(2)}</span>
      </div>
      <button className="btn" style={{ marginTop: 12 }} disabled={busy} onClick={send}>{busy ? 'Sending…' : 'Submit order'}</button>
      {error && <p className="error">{error}</p>}
    </div>
  )
}

function UploadTable({ rows }: { rows: UploadRow[] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr><th>When</th><th>File</th><th>By</th><th>Status</th><th>Orders</th><th>Value (R$)</th><th>Details</th></tr>
        </thead>
        <tbody>
          {rows.map((u) => (
            <tr key={u.upload_id}>
              <td>{new Date(u.created_at).toLocaleString()}</td>
              <td>{u.filename}</td>
              <td>{u.user_email}</td>
              <td><span className={`status ${u.status.toLowerCase()}`}>{u.status}</span></td>
              <td>{u.order_count ?? '–'}</td>
              <td>{u.total_value ? Number(u.total_value).toLocaleString(undefined, { minimumFractionDigits: 2 }) : '–'}</td>
              <td>
                {u.message}
                {u.errors && u.errors.length > 0 && (
                  <details><summary>{u.errors.length} problem(s)</summary>
                    <ul className="errors">{u.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
                  </details>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
