import { useEffect, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { apiGet } from '../api'
import { config } from '../config'
import { useUser } from '../useUser'
import StateMap, { type StateRow } from '../components/StateMap'

type DashboardData = {
  kpis: { revenue: number; orders: number; avg_delivery_days: number; late_pct: number }
  monthly: { cal_year: number; cal_month: number; revenue: number; items_sold: number }[]
  states: StateRow[]
  categories: { category: string; revenue: number; items: number }[]
  payments: { payment_type: string; payments: number; value: number }[]
  sources: { data_source: string; orders: number }[]
  generated_at: string
}

const PINKS = ['#a61e4d', '#d6336c', '#f06595', '#faa2c1', '#fcc2d7', '#862e9c']
const brl = (n: number) => `R$ ${Math.round(n).toLocaleString()}`
const short = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(0)}K` : `${n}`)

export default function Dashboard() {
  const { idToken } = useUser()
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!config.apiUrl) return
    apiGet<DashboardData>('/dashboard', idToken).then(setData).catch((e: Error) => setError(e.message))
  }, [idToken])

  if (!config.apiUrl) {
    return <><h1>Dashboard</h1><div className="card notice">The dashboard API is not connected yet. Set <code>VITE_API_URL</code> (Phase 3).</div></>
  }
  if (error) return <><h1>Dashboard</h1><div className="card notice error">Could not load data: {error}</div></>
  if (!data) return <><h1>Dashboard</h1><p className="muted">Loading data from Redshift… (the first load can take ~10 seconds)</p></>

  const k = data.kpis
  const monthly = data.monthly.map((m) => ({ ...m, label: `${m.cal_year}-${String(m.cal_month).padStart(2, '0')}` }))

  return (
    <>
      <h1>Dashboard</h1>
      <p className="muted">Data from Redshift · updated {new Date(data.generated_at).toLocaleString()}</p>

      <section className="kpis">
        <Kpi label="Total revenue (BRL)" value={brl(k.revenue)} />
        <Kpi label="Orders" value={k.orders.toLocaleString()} />
        <Kpi label="Avg delivery days" value={k.avg_delivery_days.toFixed(2)} />
        <Kpi label="Late delivery %" value={`${(k.late_pct * 100).toFixed(2)}%`} />
      </section>

      <section className="grid2">
        <div className="card">
          <h3>Revenue by month (BRL)</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={monthly}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3d9e3" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} minTickGap={20} />
              <YAxis tickFormatter={short} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v) => brl(Number(v))} />
              <Line type="monotone" dataKey="revenue" stroke="#d6336c" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <h3>Orders by state</h3>
          <StateMap rows={data.states} />
        </div>

        <div className="card">
          <h3>Top 10 categories by revenue</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={data.categories} layout="vertical" margin={{ left: 40 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3d9e3" />
              <XAxis type="number" tickFormatter={short} tick={{ fontSize: 11 }} />
              <YAxis type="category" dataKey="category" width={130} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v) => brl(Number(v))} />
              <Bar dataKey="revenue" fill="#d6336c" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <h3>Payment types</h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie data={data.payments} dataKey="payments" nameKey="payment_type" innerRadius={60} outerRadius={100}>
                {data.payments.map((_, i) => <Cell key={i} fill={PINKS[i % PINKS.length]} />)}
              </Pie>
              <Tooltip formatter={(v) => Number(v).toLocaleString()} />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <h3>Orders by data source</h3>
        <div className="sources">
          {data.sources.map((s) => (
            <div key={s.data_source}><span className="badge admin">{s.data_source}</span> {s.orders.toLocaleString()}</div>
          ))}
        </div>
      </section>
    </>
  )
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="card kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
    </div>
  )
}
