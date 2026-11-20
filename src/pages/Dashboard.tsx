const kpis = ['Total revenue (BRL)', 'Orders', 'Avg delivery days', 'Late delivery %']

export default function Dashboard() {
  return (
    <>
      <h1>Dashboard</h1>
      <p className="muted">Live numbers from Redshift appear here once the dashboard API is connected (Phase 3).</p>
      <section className="kpis">
        {kpis.map((k) => (
          <div className="card kpi" key={k}>
            <div className="kpi-label">{k}</div>
            <div className="kpi-value">—</div>
          </div>
        ))}
      </section>
      <section className="grid2">
        <div className="card placeholder">Revenue by month</div>
        <div className="card placeholder">Orders by state (map)</div>
        <div className="card placeholder">Top categories</div>
        <div className="card placeholder">Payment types</div>
      </section>
    </>
  )
}
