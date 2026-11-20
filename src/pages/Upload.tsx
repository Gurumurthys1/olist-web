import { useUser } from '../useUser'

export default function Upload() {
  const { isAdmin } = useUser()
  return (
    <>
      <h1>Upload data</h1>
      {!isAdmin ? (
        <div className="card notice">Only users in the <b>admin</b> group can upload data.</div>
      ) : (
        <div className="card">
          <p>Upload a CSV of new orders, or enter one order by hand.</p>
          <p className="muted">Coming in Phase 4: template download, file upload, validation results and processing status.</p>
        </div>
      )}
    </>
  )
}
