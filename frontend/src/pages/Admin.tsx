import { useEffect, useState } from 'react'
import { api, cap, fmtTime, num, useAction, useAuth, useFetch } from '../lib'
import { Async, Badge, Btn, Card, Empty, Field, Input, PageHeader, Select, Stat, Status, Table } from '../ui'

export function UsersPage() {
  const [role, setRole] = useState(''); const u = useFetch<any[]>(`/users${role ? `?role=${role}` : ''}`); const { run, busy } = useAction()
  const [n, setN] = useState<any>({ role: 'kitchen' })
  return (
    <div>
      <PageHeader title="User management" sub="Create kitchen staff, activate or deactivate accounts and approve redistribution partners." />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Add staff account"><div className="space-y-3"><Field label="Name"><Input value={n.name || ''} onChange={(e: any) => setN({ ...n, name: e.target.value })} /></Field><Field label="Email"><Input type="email" value={n.email || ''} onChange={(e: any) => setN({ ...n, email: e.target.value })} /></Field>
          <Field label="Temporary password" hint="8+ characters with a letter and a number"><Input type="password" value={n.password || ''} onChange={(e: any) => setN({ ...n, password: e.target.value })} /></Field>
          <Field label="Role"><Select value={n.role} onChange={(e: any) => setN({ ...n, role: e.target.value })}><option value="kitchen">Kitchen staff</option><option value="student">Student</option></Select></Field>
          <Btn loading={busy} onClick={() => run(async () => { await api('/users', { body: n }); setN({ role: 'kitchen' }); u.reload() }, 'Account created')}>Create account</Btn></div></Card>
        <Card title="Accounts" className="lg:col-span-2" action={<Select className="w-40" value={role} onChange={(e: any) => setRole(e.target.value)}><option value="">All roles</option>{['student', 'kitchen', 'mess_admin', 'ngo'].map((r) => <option key={r} value={r}>{cap(r)}</option>)}</Select>}>
          <Async f={u}>{(rows) => <Table rows={rows} cols={[{ h: 'Name', r: (r) => <div><b>{r.name}</b><div className="text-xs text-slate-500">{r.email}</div></div> }, { h: 'Role', r: (r) => <>{cap(r.role)}{r.org_name && <div className="text-xs text-slate-500">{r.org_name}</div>}</> }, { h: 'Status', r: (r) => !r.is_approved ? <Badge tone="amber">Awaiting approval</Badge> : r.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="red">Deactivated</Badge> },
            { h: '', r: (r) => r.role === 'super_admin' ? null : <div className="flex gap-1">{r.role === 'ngo' && !r.is_approved && <Btn size="sm" onClick={() => run(async () => { await api(`/users/${r.id}/approve`, { body: { approve: true } }); u.reload() }, 'Partner approved')}>Approve</Btn>}{r.role !== 'ngo' && <Btn size="sm" variant="secondary" onClick={() => run(async () => { await api(`/users/${r.id}`, { method: 'PATCH', body: { is_active: !r.is_active } }); u.reload() })}>{r.is_active ? 'Deactivate' : 'Activate'}</Btn>}</div> }]} />}</Async></Card>
      </div>
    </div>
  )
}

export function InstitutionSettings() {
  const inst = useFetch<any>('/institution'); const { run, busy } = useAction(); const [s, setS] = useState<any>(null); const [name, setName] = useState('')
  useEffect(() => { if (inst.data) { setS(JSON.parse(JSON.stringify(inst.data.settings))); setName(inst.data.name) } }, [inst.data])
  if (!s) return <Async f={inst}>{() => null}</Async>
  const set = (k: string, v: any) => setS({ ...s, [k]: v }); const el = (k: string, v: any) => setS({ ...s, eligibility: { ...s.eligibility, [k]: v } })
  return (
    <div>
      <PageHeader title="Institution settings" sub={`Data mode: ${inst.data.data_mode === 'demo' ? 'synthetic demonstration data' : 'real data'}`} action={<Btn loading={busy} onClick={() => run(async () => { await api('/institution', { method: 'PUT', body: { name, settings: s } }); inst.reload() }, 'Settings saved')}>Save changes</Btn>} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="General & forecasting"><div className="grid grid-cols-2 gap-3"><div className="col-span-2"><Field label="Institution name"><Input value={name} onChange={(e: any) => setName(e.target.value)} /></Field></div>
          <Field label="Booking cutoff (hours before meal)"><Input type="number" value={s.booking_cutoff_hours} onChange={(e: any) => set('booking_cutoff_hours', +e.target.value)} /></Field>
          <Field label="Waste alert threshold (%)"><Input type="number" value={s.waste_alert_pct} onChange={(e: any) => set('waste_alert_pct', +e.target.value)} /></Field>
          <Field label="Preparation buffer (%)"><Input type="number" value={s.prep_buffer_pct} onChange={(e: any) => set('prep_buffer_pct', +e.target.value)} /></Field>
          <Field label="Currency"><Input value={s.currency} onChange={(e: any) => set('currency', e.target.value)} /></Field></div>
          <div className="mt-4 label">Meal start times (24 h)</div><div className="grid grid-cols-4 gap-3">{Object.keys(s.meal_times).map((m) => <Field key={m} label={cap(m)}><Input value={s.meal_times[m]} onChange={(e: any) => set('meal_times', { ...s.meal_times, [m]: e.target.value })} /></Field>)}</div>
          <p className="mt-2 text-xs text-slate-400">Cutoff and times apply to meals scheduled after the change.</p></Card>
        <Card title="Redistribution eligibility rules"><div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">Defaults are illustrative only. Have your food-safety officer review these limits against local regulations before real use. Passing the rules never certifies food as safe - human review is always required.</div>
          <div className="grid grid-cols-2 gap-3"><Field label="Max hours since preparation"><Input type="number" value={s.eligibility.max_hours_since_prep} onChange={(e: any) => el('max_hours_since_prep', +e.target.value)} /></Field><Field label="Min hot-holding temp °C"><Input type="number" value={s.eligibility.hot_min_temp_c} onChange={(e: any) => el('hot_min_temp_c', +e.target.value)} /></Field>
            <Field label="Max cold-holding temp °C"><Input type="number" value={s.eligibility.cold_max_temp_c} onChange={(e: any) => el('cold_max_temp_c', +e.target.value)} /></Field><Field label="Max hours at room temp"><Input type="number" value={s.eligibility.room_temp_max_hours} onChange={(e: any) => el('room_temp_max_hours', +e.target.value)} /></Field>
            <Field label="Min hours before use-by"><Input type="number" value={s.eligibility.min_hours_before_use_by} onChange={(e: any) => el('min_hours_before_use_by', +e.target.value)} /></Field></div>
          <div className="mt-3 label">Allowed categories</div><div className="flex flex-wrap gap-3 text-sm">{['cooked', 'packaged', 'fruit', 'bakery', 'raw', 'other'].map((c) => <label key={c} className="flex items-center gap-1"><input type="checkbox" checked={s.eligibility.allowed_categories.includes(c)} onChange={(e) => el('allowed_categories', e.target.checked ? [...s.eligibility.allowed_categories, c] : s.eligibility.allowed_categories.filter((x: string) => x !== c))} />{cap(c)}</label>)}</div></Card>
      </div>
    </div>
  )
}

export function Profile() {
  const { user, refresh } = useAuth(); const { run, busy } = useAction(); const [f, setF] = useState<any>({ name: user.name, phone: user.phone || '', diet: user.profile?.diet || 'veg', hostel: user.profile?.hostel || '', dietary_notes: user.profile?.dietary_notes || '' }); const [pw, setPw] = useState({ current_password: '', new_password: '' })
  return (
    <div>
      <PageHeader title="Profile & account" sub={`${user.email} · ${cap(user.role)}`} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Profile"><div className="space-y-3"><Field label="Name"><Input value={f.name} onChange={(e: any) => setF({ ...f, name: e.target.value })} /></Field><Field label="Phone"><Input value={f.phone} onChange={(e: any) => setF({ ...f, phone: e.target.value })} /></Field>
          {user.role === 'student' && <><div className="grid grid-cols-2 gap-3"><Field label="Diet"><Select value={f.diet} onChange={(e: any) => setF({ ...f, diet: e.target.value })}>{['veg', 'egg', 'non_veg', 'vegan'].map((d) => <option key={d} value={d}>{cap(d)}</option>)}</Select></Field><Field label="Hostel"><Input value={f.hostel} onChange={(e: any) => setF({ ...f, hostel: e.target.value })} /></Field></div><Field label="Dietary notes"><Input value={f.dietary_notes} onChange={(e: any) => setF({ ...f, dietary_notes: e.target.value })} /></Field></>}
          <Btn loading={busy} onClick={() => run(async () => { await api('/auth/me', { method: 'PATCH', body: f }); await refresh() }, 'Profile updated')}>Save profile</Btn></div></Card>
        <Card title="Change password"><div className="space-y-3"><Field label="Current password"><Input type="password" autoComplete="current-password" value={pw.current_password} onChange={(e: any) => setPw({ ...pw, current_password: e.target.value })} /></Field><Field label="New password"><Input type="password" autoComplete="new-password" value={pw.new_password} onChange={(e: any) => setPw({ ...pw, new_password: e.target.value })} /></Field>
          <Btn loading={busy} onClick={() => run(async () => { await api('/auth/change-password', { body: pw }); setPw({ current_password: '', new_password: '' }) }, 'Password changed')}>Update password</Btn></div></Card>
      </div>
    </div>
  )
}

export function AdminPage() {
  const ov = useFetch<any>('/admin/overview'); const ins = useFetch<any[]>('/admin/institutions'); const audit = useFetch<any[]>('/admin/audit?limit=60'); const { run, busy } = useAction(); const [n, setN] = useState({ name: '', code: '' })
  return (
    <div>
      <PageHeader title="Platform administration" sub="Cross-institution overview, institutions and recent activity." />
      <Async f={ov}>{(o) => <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-5"><Stat label="Institutions" value={o.institutions} /><Stat label="Meal schedules" value={num(o.meal_schedules, 0)} /><Stat label="Bookings" value={num(o.bookings, 0)} /><Stat label="Surplus listings" value={o.surplus_listings} /><Stat label="Partners pending" value={o.pending_partners} tone={o.pending_partners ? 'warn' : 'good'} /></div>}</Async>
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Institutions" className="lg:col-span-2"><Async f={ins}>{(rows) => <Table rows={rows} cols={[{ h: 'Name', r: (r) => r.name }, { h: 'Code', r: (r) => r.code }, { h: 'Data', r: (r) => <Badge tone={r.data_mode === 'demo' ? 'amber' : 'green'}>{r.data_mode === 'demo' ? 'Synthetic demo' : 'Real'}</Badge> }, { h: 'Users', r: (r) => r.users }]} />}</Async>
          <p className="mt-3 text-xs text-slate-500">To act inside another institution, send the X-Institution-Id header via the API; the UI works within your home institution.</p></Card>
        <Card title="Add institution"><div className="space-y-3"><Field label="Name"><Input value={n.name} onChange={(e: any) => setN({ ...n, name: e.target.value })} /></Field><Field label="Code"><Input value={n.code} onChange={(e: any) => setN({ ...n, code: e.target.value })} /></Field><Btn loading={busy} onClick={() => run(async () => { await api('/admin/institutions', { body: n }); setN({ name: '', code: '' }); ins.reload() }, 'Institution created')}>Create</Btn></div></Card>
      </div>
      <Card title="Recent activity (audit log)" className="mt-6"><Async f={audit}>{(rows) => <Table rows={rows} cols={[{ h: 'When', r: (r) => fmtTime(r.created_at) }, { h: 'User', r: (r) => r.user || '-' }, { h: 'Action', r: (r) => r.action }, { h: 'Detail', r: (r) => r.detail || '' }]} />}</Async></Card>
    </div>
  )
}
