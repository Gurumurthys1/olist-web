import { useAuth } from 'react-oidc-context'
import { Navigate, Route, Routes } from 'react-router-dom'
import { isConfigured } from './config'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Upload from './pages/Upload'
import Ask from './pages/Ask'
import Status from './pages/Status'

export default function App() {
  const auth = useAuth()

  if (!isConfigured) {
    return (
      <Center>
        <h1>Setup needed</h1>
        <p>Copy <code>.env.example</code> to <code>.env.local</code>, fill in the Cognito values, then restart <code>npm run dev</code>.</p>
      </Center>
    )
  }
  if (auth.isLoading) return <Center><p>Loading…</p></Center>
  if (auth.error) {
    return (
      <Center>
        <h1>Login error</h1>
        <p className="error">{auth.error.message}</p>
        <button className="btn" onClick={() => auth.signinRedirect()}>Try again</button>
      </Center>
    )
  }
  if (!auth.isAuthenticated) {
    return (
      <Center>
        <div className="brand-big">Olist <span>Analytics</span></div>
        <p className="muted">Brazilian e-commerce sales, delivery and payments on AWS.</p>
        <button className="btn" onClick={() => auth.signinRedirect()}>Sign in</button>
      </Center>
    )
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/upload" element={<Upload />} />
        <Route path="/ask" element={<Ask />} />
        <Route path="/status" element={<Status />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

function Center({ children }: { children: React.ReactNode }) {
  return <main className="center">{children}</main>
}
