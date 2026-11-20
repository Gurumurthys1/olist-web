import { NavLink, Outlet } from 'react-router-dom'
import { useUser } from '../useUser'

const links = [
  { to: '/', label: 'Dashboard' },
  { to: '/upload', label: 'Upload data' },
  { to: '/ask', label: 'Ask AI' },
  { to: '/status', label: 'Status' },
]

export default function Layout() {
  const { email, isAdmin, logout } = useUser()
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">Olist <span>Analytics</span></div>
        <nav>
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.to === '/'}>{l.label}</NavLink>
          ))}
        </nav>
        <div className="who">
          <span title={email}>{email}</span>
          <span className={isAdmin ? 'badge admin' : 'badge'}>{isAdmin ? 'admin' : 'viewer'}</span>
          <button className="btn small ghost" onClick={logout}>Sign out</button>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
