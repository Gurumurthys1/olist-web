export default function Ask() {
  return (
    <>
      <h1>Ask AI</h1>
      <div className="card">
        <p>Ask a question about the sales data in plain English, for example
          <i> "Top 5 states by revenue last month"</i>.</p>
        <p className="muted">Coming in Phase 6: the AI writes safe read-only SQL, runs it on Redshift and explains the answer.</p>
      </div>
    </>
  )
}
