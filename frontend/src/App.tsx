import { useEffect, useState } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Activity, Bell, BookOpen, Bot, Camera, ChefHat, ClipboardList, Gauge, HeartHandshake, History, Home, Leaf, LogOut, Menu as MenuIcon, Settings, Sparkles, Trash2, UserCog, Users, Utensils, Warehouse } from 'lucide-react'
import { api, fmtTime, useAuth, useFetch } from './lib'
import { DemoBanner, Loading } from './ui'
import { Forgot, Landing, Login, Register } from './pages/Public'
import { BookMeals, MealHistory, StudentDashboard } from './pages/Student'
import { ManagerDashboard, MenuManagement, MenuOptimisation, Prediction, Preparation, WasteAnalytics } from './pages/Manager'
import { Alerts, Partner, Surplus, Sustainability, Vision } from './pages/Ops'
import { AdminPage, InstitutionSettings, Profile, UsersPage } from './pages/Admin'

const mgr: [string, string, any][] = [['/', 'Dashboard', Home], ['/prediction', 'Demand prediction', Gauge], ['/prep', 'Preparation', ChefHat], ['/waste', 'Waste analytics', Trash2], ['/menu', 'Menu management', Utensils],
  ['/menu-opt', 'Menu optimisation', Sparkles], ['/vision', 'Image recognition', Camera], ['/surplus', 'Surplus & donations', HeartHandshake], ['/alerts', 'Smart alerts', Bell], ['/sustainability', 'Sustainability', Leaf], ['/users', 'Users', Users], ['/settings', 'Institution settings', Settings]]
const NAV: Record<string, [string, string, any][]> = {
  student: [['/', 'Dashboard', Home], ['/book', 'Book meals', BookOpen], ['/history', 'Meal history', History]],
  mess_admin: mgr,
  super_admin: [...mgr, ['/admin', 'Platform admin', UserCog]],
  kitchen: [['/', 'Dashboard', Home], ['/prep', 'Preparation', ChefHat], ['/prediction', 'Demand prediction', Gauge], ['/waste', 'Waste analytics', Trash2], ['/vision', 'Image recognition', Camera], ['/surplus', 'Surplus', HeartHandshake], ['/alerts', 'Smart alerts', Bell], ['/sustainability', 'Sustainability', Leaf]],
  ngo: [['/', 'Surplus & requests', HeartHandshake]],
}

function Bell_() {
  const [open, setOpen] = useState(false)
  const f = useFetch<any>('/notifications')
  useEffect(() => { const t = setInterval(f.reload, 60000); return () => clearInterval(t) }, [f.reload])
  const nav = useNavigate()
  const d = f.data
  return (
    <div className="relative">
      <button aria-label="Notifications" className="relative rounded-lg p-2 hover:bg-slate-100" onClick={() => { setOpen(!open); if (!open) f.reload() }}>
        <Bell className="h-5 w-5" />{d?.unread > 0 && <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-600 px-1 text-[10px] text-white">{d.unread}</span>}
      </button>
      {open && <div className="card absolute right-0 z-30 mt-2 w-80 max-w-[90vw]">
        <div className="flex items-center justify-between border-b px-3 py-2 text-sm font-semibold">Notifications<button className="text-xs font-normal text-brand-700" onClick={async () => { await api('/notifications/read-all', { method: 'POST' }); f.reload() }}>Mark all read</button></div>
        <ul className="max-h-80 divide-y overflow-y-auto">{d?.items?.length ? d.items.map((n: any) => <li key={n.id} className={`cursor-pointer px-3 py-2 text-sm hover:bg-slate-50 ${n.is_read ? 'text-slate-500' : ''}`} onClick={async () => { await api(`/notifications/${n.id}/read`, { method: 'POST' }); setOpen(false); if (n.link) nav(n.link); f.reload() }}><div className="font-medium">{n.title}</div>{n.body && <div className="text-xs">{n.body}</div>}<div className="text-[11px] text-slate-400">{fmtTime(n.created_at)}</div></li>) : <li className="px-3 py-6 text-center text-sm text-slate-400">Nothing yet</li>}</ul>
      </div>}
    </div>
  )
}

function Shell() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  useEffect(() => setOpen(false), [loc.pathname])
  const items = NAV[user.role] || []
  const role = user.role
  const H = role === 'student' ? StudentDashboard : role === 'ngo' ? Partner : ManagerDashboard
  return (
    <div className="min-h-screen">
      <DemoBanner user={user} />
      <div className="flex">
        <aside className={`fixed inset-y-0 left-0 z-30 w-64 transform border-r border-slate-200 bg-white transition-transform lg:static lg:translate-x-0 ${open ? 'translate-x-0' : '-translate-x-full'}`} style={{ top: 0 }}>
          <div className="flex h-14 items-center gap-2 border-b px-4"><div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white"><Activity className="h-4 w-4" /></div><div><div className="text-sm font-semibold leading-none">Shakambari AI</div><div className="text-[10px] text-slate-400">Think Smart. Serve Right. Waste Less.</div></div></div>
          <nav className="space-y-0.5 p-3" aria-label="Main">{items.map(([to, label, Icon]) => <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${isActive ? 'bg-brand-50 font-medium text-brand-700' : 'text-slate-600 hover:bg-slate-100'}`}><Icon className="h-4 w-4" />{label}</NavLink>)}</nav>
        </aside>
        {open && <div className="fixed inset-0 z-20 bg-slate-900/30 lg:hidden" onClick={() => setOpen(false)} />}
        <div className="min-w-0 flex-1">
          <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b border-slate-200 bg-white/90 px-4 backdrop-blur">
            <button aria-label="Open menu" className="rounded-lg p-2 hover:bg-slate-100 lg:hidden" onClick={() => setOpen(true)}><MenuIcon className="h-5 w-5" /></button>
            <div className="hidden text-sm text-slate-500 lg:block">{user.institution?.name || 'Redistribution partner'}</div>
            <div className="flex items-center gap-2">
              <Bell_ />
              <Link to="/profile" className="rounded-lg px-3 py-1.5 text-sm hover:bg-slate-100"><span className="font-medium">{user.name}</span> <span className="text-xs text-slate-400">({user.role.replace('_', ' ')})</span></Link>
              <button aria-label="Log out" className="rounded-lg p-2 hover:bg-slate-100" onClick={logout}><LogOut className="h-4 w-4" /></button>
            </div>
          </header>
          <main className="mx-auto max-w-7xl p-4 lg:p-8">
            <Routes>
              <Route path="/" element={<H />} />
              {role === 'student' && <><Route path="/book" element={<BookMeals />} /><Route path="/history" element={<MealHistory />} /></>}
              {role !== 'student' && role !== 'ngo' && <>
                <Route path="/prediction" element={<Prediction />} /><Route path="/prep" element={<Preparation />} /><Route path="/waste" element={<WasteAnalytics />} />
                <Route path="/vision" element={<Vision />} /><Route path="/surplus" element={<Surplus />} /><Route path="/alerts" element={<Alerts />} /><Route path="/sustainability" element={<Sustainability />} />
              </>}
              {(role === 'mess_admin' || role === 'super_admin') && <>
                <Route path="/menu" element={<MenuManagement />} /><Route path="/menu-opt" element={<MenuOptimisation />} /><Route path="/users" element={<UsersPage />} /><Route path="/settings" element={<InstitutionSettings />} />
              </>}
              {role === 'super_admin' && <Route path="/admin" element={<AdminPage />} />}
              <Route path="/profile" element={<Profile />} />
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </main>
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const { user, ready } = useAuth()
  if (!ready) return <Loading />
  return (
    <Routes>
      {!user ? <>
        <Route path="/" element={<Landing />} /><Route path="/login" element={<Login />} /><Route path="/register" element={<Register />} /><Route path="/forgot-password" element={<Forgot />} /><Route path="*" element={<Navigate to="/login" />} />
      </> : <Route path="/login" element={<Navigate to="/" />} />}
      {user && <Route path="/*" element={<Shell />} />}
    </Routes>
  )
}
