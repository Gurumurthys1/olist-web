import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost } from '../api'
import { config } from '../config'
import { useUser } from '../useUser'
import { SUGGESTIONS, newId, recentIds, rememberId, toCsv } from '../samples'
import { STATES, TABLES, type Column, type TableSpec } from '../tables'

type UploadRow = {
  upload_id: string; created_at: string; user_email: string; filename: string; table_name?: string
  status: string; message: string; errors?: string[]; row_count?: string; order_count?: string
}
type Preview = { columns: string[]; sample: Record<string, unknown>[]; uploaded: Record<string, unknown>[] }
type PipelineRun = { name?: string; status: string; started?: string; stopped?: string | null }
type UploadsReply = { uploads: UploadRow[]; ready_count?: number; pipeline?: PipelineRun | null }

/** Ask the API for a presigned URL, then send the CSV straight to S3. */
async function sendCsv(table: string, filename: string, csv: Blob, idToken: string) {
  const { url, upload_id } = await apiPost<{ url: string; upload_id: string }>('/uploads', { table, filename }, idToken)
  const res = await fetch(url, { method: 'PUT', headers: { 'Content-Type': 'text/csv' }, body: csv })
  if (!res.ok) throw new Error(`S3 upload failed: ${res.status} ${await res.text()}`)
  return upload_id
}

/** Example row for the template: generated ids where no example is given. */
const exampleRow = (t: TableSpec) =>
  Object.fromEntries(t.columns.map((col) => [col.name, col.example || (col.kind === 'id' ? newId() : '')]))

export default function Upload() {
  const { isAdmin, idToken } = useUser()
  const [table, setTable] = useState<TableSpec>(TABLES[0])
  const [uploads, setUploads] = useState<UploadRow[]>([])
  const [listError, setListError] = useState('')
  const [msg, setMsg] = useState('')
  const [readyTotal, setReadyTotal] = useState(0)
  const [pipeline, setPipeline] = useState<PipelineRun | null>(null)

  const load = useCallback(() => {
    apiGet<UploadsReply>('/uploads', idToken)
      .then((r) => {
        setUploads(r.uploads); setListError('')
        setReadyTotal(r.ready_count ?? 0); setPipeline(r.pipeline ?? null)
      })
      .catch((e: Error) => setListError(e.message))
  }, [idToken])

  useEffect(() => { if (config.apiUrl) load() }, [load])

  // refresh the list every 4 s while a recent file (last 5 minutes) is being checked,
  // and every 15 s while the pipeline runs
  const busy = uploads.some((u) => (u.status === 'WAITING_FILE' || u.status === 'VALIDATING')
    && Date.now() - new Date(u.created_at).getTime() < 5 * 60 * 1000)
  const running = pipeline?.status === 'RUNNING'
  useEffect(() => {
    if (!busy && !running) return
    const t = setInterval(load, busy ? 4000 : 15000)
    return () => clearInterval(t)
  }, [busy, running, load])

  // reload the preview whenever an upload becomes READY or LOADED, so its rows show up
  const readyCount = uploads.filter((u) => u.status === 'READY' || u.status === 'LOADED').length

  const afterSend = (id: string) => { setMsg(`Sent ${table.label} (upload ${id}). Checking it now…`); setTimeout(load, 1500) }

  if (!isAdmin) {
    return <><h1>Upload data</h1><div className="card notice">Only users in the <b>admin</b> group can upload data.</div></>
  }

  return (
    <>
      <h1>Upload data</h1>
      <p className="muted">
        Pick a table, then upload a CSV or enter one row. Every row is checked first. Valid rows are loaded
        into Redshift and QuickSight automatically; a row with an existing id replaces the old one.
      </p>
      {msg && <div className="card notice" style={{ marginBottom: 16 }}>{msg}</div>}

      <PipelineCard run={pipeline} readyTotal={readyTotal} idToken={idToken} onStarted={(m) => { setMsg(m); setTimeout(load, 2000) }} />

      <section className="upload-layout">
        <div className="card">
          <h3>1. Choose a table</h3>
          <div className="table-pills">
            {TABLES.map((t) => (
              <button key={t.name} className={`pill ${t.name === table.name ? 'active' : ''}`}
                onClick={() => { setTable(t); setMsg('') }}>{t.label}</button>
            ))}
          </div>
          <p className="muted small" style={{ marginTop: 12 }}>{table.about}</p>
          <p className="small"><b>Columns</b> (<span className="req">*</span> required):</p>
          <ul className="col-list small">
            {table.columns.map((col) => (
              <li key={col.name}><code>{col.name}</code>{col.required && <span className="req">*</span>}
                <span className="muted"> {hint(col)}</span></li>
            ))}
          </ul>
        </div>

        <div className="card">
          <h3>2. Add data to <span className="accent">{table.label}</span></h3>
          <AddData key={table.name} table={table} idToken={idToken} onSent={afterSend} />
        </div>
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <TablePreview key={`${table.name}-${readyCount}`} table={table} idToken={idToken} />
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

const STEPS = 'API ingest → Glue job 1 → Glue job 2 → Redshift load → mark uploads LOADED + QuickSight refresh'

function PipelineCard({ run, readyTotal, idToken, onStarted }: {
  run: PipelineRun | null; readyTotal: number; idToken: string; onStarted: (msg: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const running = run?.status === 'RUNNING'

  const start = async () => {
    if (!window.confirm(`Start the pipeline now?\n\n${STEPS}\n\nIt takes about 10–15 minutes.`)) return
    setBusy(true); setError('')
    try {
      const r = await apiPost<{ started: string }>('/process', {}, idToken)
      onStarted(`Pipeline started (${r.started}). This page updates by itself; it takes about 10–15 minutes.`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const when = (s?: string | null) => (s ? new Date(s).toLocaleString() : '')
  return (
    <section className="card pipeline">
      <div>
        <h3>Load into Redshift</h3>
        <p className="small">
          A valid upload starts the pipeline by itself (Redshift, then QuickSight). It also runs every night at 02:00
          with the new API data. <b>{readyTotal}</b> upload(s) READY, waiting to load.
        </p>
        {run && run.status !== 'NEVER_RUN' && (
          <p className="small muted">
            Last run: <span className={`status ${run.status.toLowerCase()}`}>{run.status}</span>{' '}
            started {when(run.started)}{run.stopped ? `, finished ${when(run.stopped)}` : ''}
          </p>
        )}
        {run === null && <p className="small muted">Pipeline status is not connected yet (PIPELINE_ARN).</p>}
        {error && <p className="error small">{error}</p>}
      </div>
      <button className="btn" disabled={busy || running} onClick={start}>
        {running ? 'Running…' : busy ? 'Starting…' : 'Process now'}
      </button>
    </section>
  )
}

function hint(col: Column) {
  if (col.ref) return `must exist in ${col.ref}s`
  switch (col.kind) {
    case 'id': return '32 characters 0-9 a-f'
    case 'ts': return 'date/time, e.g. 2018-10-25 14:30:00'
    case 'zip': return '5 digits'
    case 'state': return 'state code, e.g. SP'
    case 'enum': return (col.values ?? []).join(' / ')
    case 'int': return 'whole number'
    case 'num': return 'number'
    default: return ''
  }
}

function AddData({ table, idToken, onSent }: { table: TableSpec; idToken: string; onSent: (id: string) => void }) {
  const [mode, setMode] = useState<'csv' | 'row'>('row')
  return (
    <>
      <div className="tabs">
        <button className={mode === 'row' ? 'active' : ''} onClick={() => setMode('row')}>Enter one row</button>
        <button className={mode === 'csv' ? 'active' : ''} onClick={() => setMode('csv')}>Upload CSV</button>
      </div>
      {mode === 'csv'
        ? <CsvUpload table={table} idToken={idToken} onSent={onSent} />
        : <RowForm table={table} idToken={idToken} onSent={onSent} />}
    </>
  )
}

function CsvUpload({ table, idToken, onSent }: { table: TableSpec; idToken: string; onSent: (id: string) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const downloadTemplate = () => {
    const csv = toCsv(table.columns.map((col) => col.name), [exampleRow(table)])
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    a.download = `olist_${table.name}_template.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const send = async () => {
    if (!file) return
    setBusy(true); setError('')
    try {
      onSent(await sendCsv(table.name, file.name, file, idToken))
      setFile(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <p className="muted small">The first row must be the column names of <b>{table.label}</b>. Up to 1000 rows.
        The template has the right columns and one example row.</p>
      <button className="btn small ghost" onClick={downloadTemplate}>Download {table.label} template</button>
      <div className="form-row" style={{ marginTop: 12 }}>
        <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </div>
      <button className="btn" disabled={!file || busy} onClick={send}>{busy ? 'Uploading…' : 'Upload'}</button>
      {error && <p className="error">{error}</p>}
    </>
  )
}

/** Starting values: a fresh id for new keys, examples elsewhere. */
function startValues(table: TableSpec) {
  return Object.fromEntries(table.columns.map((col) => {
    if (col.kind === 'id' && !col.ref && !col.example) return [col.name, newId()]
    if (col.kind === 'ts') return [col.name, col.example ? col.example.slice(0, 16).replace(' ', 'T') : '']
    return [col.name, col.example]
  }))
}

function RowForm({ table, idToken, onSent }: { table: TableSpec; idToken: string; onSent: (id: string) => void }) {
  const [values, setValues] = useState<Record<string, string>>(() => startValues(table))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = (name: string, v: string) => setValues({ ...values, [name]: v })

  const send = async () => {
    const empty = table.columns.filter((col) => col.required && !values[col.name]?.trim())
    if (empty.length) { setError(`Please fill in: ${empty.map((col) => col.name).join(', ')}`); return }
    setBusy(true); setError('')
    try {
      const row = Object.fromEntries(table.columns.map((col) => {
        const v = (values[col.name] ?? '').trim()
        return [col.name, col.kind === 'ts' && v ? `${v.replace('T', ' ')}:00`.slice(0, 19) : v]
      }))
      const keyCol = table.columns[0].name
      const id = await sendCsv(table.name, `form_${table.name}_${row[keyCol].slice(0, 8)}.csv`,
        new Blob([toCsv(table.columns.map((col) => col.name), [row])], { type: 'text/csv' }), idToken)
      if (table.makes) rememberId(table.makes, row[keyCol])
      onSent(id)
      setValues(startValues(table))  // ready for the next row, with new ids
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="form-grid">
        {table.columns.map((col) => (
          <label key={col.name} className={col.kind === 'text' ? 'wide' : ''}>
            <span>{col.name}{col.required && <span className="req">*</span>}</span>
            <Field col={col} value={values[col.name] ?? ''} onChange={(v) => set(col.name, v)} />
          </label>
        ))}
      </div>
      <button className="btn" disabled={busy} onClick={send}>{busy ? 'Sending…' : `Add to ${table.label}`}</button>
      {error && <p className="error">{error}</p>}
    </>
  )
}

function Field({ col, value, onChange }: { col: Column; value: string; onChange: (v: string) => void }) {
  if (col.kind === 'enum' || col.kind === 'state') {
    const options = col.kind === 'state' ? STATES : col.values ?? []
    return (
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {!col.required && <option value="">(empty)</option>}
        {options.map((o) => <option key={o}>{o}</option>)}
      </select>
    )
  }
  if (col.kind === 'ts') {
    return <input type="datetime-local" value={value} onChange={(e) => onChange(e.target.value)} />
  }
  if (col.kind === 'int' || col.kind === 'num') {
    return <input type="number" step={col.kind === 'int' ? 1 : 'any'} value={value} onChange={(e) => onChange(e.target.value)} />
  }
  if (col.ref) {
    const listId = `list-${col.ref}`
    const options = [...recentIds(col.ref), ...(SUGGESTIONS[col.ref] ?? [])]
    return (
      <>
        <input type="text" list={listId} value={value} onChange={(e) => onChange(e.target.value)} placeholder={`pick or paste a ${col.ref}`} />
        <datalist id={listId}>{options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}</datalist>
      </>
    )
  }
  if (col.kind === 'id') {
    return (
      <div className="id-field">
        <input type="text" value={value} onChange={(e) => onChange(e.target.value)} />
        <button type="button" className="btn small ghost" onClick={() => onChange(newId())} title="Generate a new id">New</button>
      </div>
    )
  }
  return <input type="text" value={value} onChange={(e) => onChange(e.target.value)} />
}

function TablePreview({ table, idToken }: { table: TableSpec; idToken: string }) {
  const [data, setData] = useState<Preview | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    apiGet<Preview>(`/preview?table=${table.name}`, idToken).then(setData).catch((e: Error) => setError(e.message))
  }, [table.name, idToken])

  const columns = table.columns.map((col) => col.name)
  return (
    <>
      <h3>Preview: {table.label}</h3>
      {error && <p className="error">Could not load the preview: {error}</p>}
      {!error && !data && <p className="muted">Loading…</p>}
      {data && (
        <>
          <p className="small"><b>Added from the website</b> <span className="muted">(newest first, waiting for or already in Redshift)</span></p>
          {data.uploaded.length === 0
            ? <p className="muted small">Nothing uploaded to this table yet.</p>
            : <RowsTable columns={columns} rows={data.uploaded} />}
          <p className="small" style={{ marginTop: 16 }}><b>Original Olist data</b> <span className="muted">(first {data.sample.length} rows)</span></p>
          <RowsTable columns={columns} rows={data.sample} />
        </>
      )}
    </>
  )
}

function RowsTable({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  const show = (v: unknown) => {
    const s = v == null ? '' : String(v)
    return /^[0-9a-f]{32}$/.test(s) ? <span title={s}>{s.slice(0, 8)}…</span> : s
  }
  return (
    <div className="table-wrap">
      <table className="table">
        <thead><tr>{columns.map((col) => <th key={col}>{col}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => <tr key={i}>{columns.map((col) => <td key={col}>{show(r[col])}</td>)}</tr>)}
        </tbody>
      </table>
    </div>
  )
}

function UploadTable({ rows }: { rows: UploadRow[] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr><th>When</th><th>Table</th><th>File</th><th>By</th><th>Status</th><th>Rows</th><th>Details</th></tr>
        </thead>
        <tbody>
          {rows.map((u) => (
            <tr key={u.upload_id}>
              <td>{new Date(u.created_at).toLocaleString()}</td>
              <td>{u.table_name ?? 'orders'}</td>
              <td>{u.filename}</td>
              <td>{u.user_email}</td>
              <td><span className={`status ${u.status.toLowerCase()}`}>{u.status}</span></td>
              <td>{u.row_count ?? u.order_count ?? '–'}</td>
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
