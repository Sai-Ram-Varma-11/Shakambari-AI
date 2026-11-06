import { FormEvent, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Activity, BarChart3, ChefHat, Gauge, HeartHandshake, Leaf, Sparkles, Users, Bell } from 'lucide-react'
import { api, useAction, useAuth } from '../lib'
import { Btn, Field, Input, Select } from '../ui'

const MODULES = [
  [Gauge, 'AI demand prediction', 'Forecasts attendance and dish-wise quantities from bookings, history and calendar, with uncertainty ranges.'],
  [BarChart3, 'Food waste analytics', 'Prepared vs consumed vs leftover, edible vs inedible, cost of waste and recurring patterns.'],
  [HeartHandshake, 'Intelligent redistribution', 'Human-verified surplus listings and an approval workflow with verified partners.'],
  [Users, 'Student demand intelligence', 'Meal booking, cancellations, attendance and ratings that feed the forecast.'],
  [Sparkles, 'AI menu optimisation', 'Evidence-based portion and menu suggestions from waste and feedback history.'],
  [ChefHat, 'Simple cooking recommendations', 'Clear suggestions based on recent leftovers help the mess plan what to cook and how much.'],
  [Bell, 'Smart alerts', 'Explainable alerts: what happened, the data behind it, why it matters, what to do.'],
  [Leaf, 'Sustainability dashboard', 'Measured, calculated and estimated impact kept clearly separate.'],
] as const

export function Landing() {
  return (
    <div className="min-h-screen bg-white">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
        <div className="flex items-center gap-2 font-semibold"><div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white"><Activity className="h-4 w-4" /></div>Shakambari AI</div>
        <div className="flex gap-2"><Link to="/register" className="btn-primary">Register</Link><Link to="/request-mess" className="btn-secondary">Register a mess</Link></div>
      </header>
      <section className="mx-auto max-w-6xl px-4 py-16 md:py-24">
        <p className="mb-3 text-sm font-medium text-brand-700">Food management for campuses, hostels and canteens</p>
        <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-slate-900 md:text-5xl">Think Smart. Serve Right. Waste Less.</h1>
        <p className="mt-5 max-w-2xl text-lg text-slate-600">Shakambari AI connects student meal bookings, kitchen preparation, waste records and verified food redistribution for a strict lacto-vegetarian food ecosystem.</p>
        <div className="mt-8 flex flex-wrap gap-3"><Link to="/register" className="btn-primary px-5 py-2.5">Get started</Link><DemoButtons buttonClass="px-5 py-2.5" /><Link to="/request-mess" className="btn-secondary px-5 py-2.5">Register a mess</Link></div>
      </section>
      <section className="border-t bg-slate-50 py-14">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="text-xl font-semibold">One connected platform, eight modules</h2>
          <p className="mt-1 text-sm text-slate-500">Bookings feed predictions, kitchen records feed waste analytics, waste history improves the next prediction, and surplus flows to partners.</p>
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{MODULES.map(([Icon, t, d]) => <div key={t} className="card p-5"><Icon className="mb-3 h-5 w-5 text-brand-600" /><div className="font-medium">{t}</div><p className="mt-1 text-sm text-slate-500">{d}</p></div>)}</div>
        </div>
      </section>
      <footer className="py-8 text-center text-xs text-slate-400">Shakambari AI · Strictly lacto-vegetarian</footer>
    </div>
  )
}

const DEMO_USERS = [
  { label: 'Super Admin', email: 'superadmin@platesense.demo' },
  { label: 'Mess Admin', email: 'manager@platesense.demo' },
  { label: 'Student', email: 'student001@students.platesense.demo' },
  { label: 'NGO / Org', email: 'ngo@platesense.demo' },
]

function DemoButtons({ buttonClass = '' }: { buttonClass?: string }) {
  const { login } = useAuth()
  const { run, busy } = useAction()
  return <>{DEMO_USERS.map((account) => <Btn key={account.email} variant="secondary" className={buttonClass} loading={busy} onClick={() => run(() => login(account.email, 'Demo@12345'))}>{account.label}</Btn>)}</>
}

function AuthFrame({ title, sub, children }: any) {
  return <div className="flex min-h-screen items-center justify-center bg-slate-50 p-4"><div className="w-full max-w-md"><Link to="/" className="mb-6 flex items-center justify-center gap-2 font-semibold"><div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white"><Activity className="h-4 w-4" /></div>Shakambari AI</Link><div className="card p-6"><h1 className="text-xl font-semibold">{title}</h1><p className="mb-5 mt-1 text-sm text-slate-500">{sub}</p>{children}</div></div></div>
}

export function Register() {
  const nav = useNavigate(); const { run, busy } = useAction()
  const [role, setRole] = useState('student'); const [insts, setInsts] = useState<any[]>([]); const [f, setF] = useState<any>({ diet: 'veg' }); const [done, setDone] = useState(''); const [err, setErr] = useState('')
  useEffect(() => { api('/auth/institutions').then((d) => { setInsts(d); if (d[0]) setF((p: any) => ({ ...p, institution_id: d[0].id })) }).catch(() => {}) }, [])
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value })
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr('')
    const r = await run(() => api('/auth/register', { body: { ...f, role, institution_id: role === 'student' ? Number(f.institution_id) : undefined } }))
    if (r) { setDone(r.message); if (role === 'student') setTimeout(() => nav('/'), 1500) }
  }
  if (done) return <AuthFrame title="You're registered" sub={done}><Link className="btn-primary w-full" to="/">Return home</Link></AuthFrame>
  return (
    <AuthFrame title="Create your account" sub="Students book meals; partner organisations request surplus food (approval required).">
      <div className="mb-4 grid grid-cols-2 gap-2 rounded-lg bg-slate-100 p-1 text-sm">{[['student', 'Student'], ['ngo', 'Partner / NGO']].map(([k, l]) => <button type="button" key={k} onClick={() => setRole(k)} className={`rounded-md py-1.5 font-medium ${role === k ? 'bg-white shadow-sm' : 'text-slate-500'}`}>{l}</button>)}</div>
      <form onSubmit={submit} className="space-y-3">
        <Field label="Full name"><Input required minLength={2} onChange={set('name')} /></Field>
        <Field label="Email"><Input type="email" required onChange={set('email')} /></Field>
        <Field label="Password" hint="At least 8 characters with a letter and a number"><Input type="password" required minLength={8} autoComplete="new-password" onChange={set('password')} /></Field>
        {role === 'student' ? <>
          <Field label="Institution"><Select required value={f.institution_id || ''} onChange={set('institution_id')}>{insts.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}</Select></Field>
          <div className="grid grid-cols-2 gap-3"><Field label="Diet"><Select value={f.diet} onChange={set('diet')}><option value="veg">Lacto-vegetarian</option><option value="vegan">Vegan</option></Select></Field><Field label="Hostel / block"><Input onChange={set('hostel')} /></Field></div>
        </> : <>
          <Field label="Organisation name"><Input required onChange={set('org_name')} /></Field>
          <Field label="Registration number" hint="Self-declared; verified manually by the mess administrator"><Input onChange={set('registration_no')} /></Field>
          <Field label="Address"><Input onChange={set('address')} /></Field>
        </>}
        <Btn type="submit" loading={busy} className="w-full">Register</Btn>
        <p className="text-center text-sm text-slate-500">Already registered? <Link className="text-brand-700" to="/">Choose a dashboard</Link></p>
      </form>
    </AuthFrame>
  )
}

export function RequestMess() {
  const { run, busy } = useAction()
  const [submitted, setSubmitted] = useState(false)
  const [f, setF] = useState<any>({ name: '', code: '', manager_name: '', email: '', password: '', phone: '' })
  const set = (key: string) => (e: any) => setF({ ...f, [key]: e.target.value })
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const result = await run(() => api('/admin/institution-requests', { body: f }))
    if (result) setSubmitted(true)
  }
  return <AuthFrame title={submitted ? 'Request sent' : 'Register a mess'} sub={submitted ? 'A super administrator will review your request. You can sign in as mess admin after approval.' : 'Request a mess account. Your login will be available after approval.'}>
    {submitted ? <Link to="/" className="btn-primary w-full">Return home</Link> : <form onSubmit={submit} className="space-y-3">
      <Field label="Mess / institution name"><Input required minLength={2} maxLength={200} value={f.name} onChange={set('name')} /></Field>
      <Field label="Mess code" hint="Use letters, numbers, hyphens or underscores"><Input required minLength={2} maxLength={40} pattern="[A-Za-z0-9_-]+" value={f.code} onChange={set('code')} /></Field>
      <Field label="Manager name"><Input required minLength={2} maxLength={120} value={f.manager_name} onChange={set('manager_name')} /></Field>
      <Field label="Manager email"><Input type="email" required value={f.email} onChange={set('email')} /></Field>
      <Field label="Password" hint="At least 8 characters"><Input type="password" required minLength={8} maxLength={128} value={f.password} onChange={set('password')} /></Field>
      <Field label="Phone (optional)"><Input value={f.phone} maxLength={30} onChange={set('phone')} /></Field>
      <Btn type="submit" loading={busy} className="w-full">Send approval request</Btn>
    </form>}
  </AuthFrame>
}

export function Forgot() {
  const { run, busy } = useAction(); const [email, setEmail] = useState(''); const [msg, setMsg] = useState(''); const [token, setToken] = useState(''); const [pw, setPw] = useState(''); const [done, setDone] = useState(false)
  return (
    <AuthFrame title="Reset password" sub="Enter your email to receive a reset token.">
      {done ? <div className="space-y-3"><p className="text-sm text-emerald-700">Password updated.</p><Link to="/" className="btn-primary w-full">Return home</Link></div> : <div className="space-y-3">
        <Field label="Email"><Input type="email" value={email} onChange={(e: any) => setEmail(e.target.value)} /></Field>
        <Btn loading={busy} className="w-full" onClick={async () => { const r = await run(() => api('/auth/forgot-password', { body: { email } })); if (r) { setMsg(r.message); if (r.dev_reset_token) setToken(r.dev_reset_token) } }}>Send reset token</Btn>
        {msg && <p className="text-sm text-slate-600">{msg} Ask your administrator for the token if email delivery is not configured (it is printed in the server log).</p>}
        {msg && <><Field label="Reset token"><Input value={token} onChange={(e: any) => setToken(e.target.value)} /></Field><Field label="New password"><Input type="password" value={pw} onChange={(e: any) => setPw(e.target.value)} /></Field>
          <Btn loading={busy} className="w-full" onClick={async () => { const r = await run(() => api('/auth/reset-password', { body: { token, new_password: pw } })); if (r) setDone(true) }}>Set new password</Btn></>}
        <Link className="block text-center text-sm text-brand-700" to="/">Back to home</Link>
      </div>}
    </AuthFrame>
  )
}
