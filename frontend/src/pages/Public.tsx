import { FormEvent, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Activity, BarChart3, Camera, Gauge, HeartHandshake, Leaf, Sparkles, Users, Bell } from 'lucide-react'
import { api, useAction, useAuth } from '../lib'
import { Btn, ErrorBox, Field, Input, Select } from '../ui'

const MODULES = [
  [Gauge, 'AI demand prediction', 'Forecasts attendance and dish-wise quantities from bookings, history and calendar, with uncertainty ranges.'],
  [BarChart3, 'Food waste analytics', 'Prepared vs consumed vs leftover, edible vs inedible, cost of waste and recurring patterns.'],
  [HeartHandshake, 'Intelligent redistribution', 'Human-verified surplus listings and an approval workflow with verified partners.'],
  [Users, 'Student demand intelligence', 'Meal booking, cancellations, attendance and ratings that feed the forecast.'],
  [Sparkles, 'AI menu optimisation', 'Evidence-based portion and menu suggestions from waste and feedback history.'],
  [Camera, 'Waste image observation', 'Photo-based classification suggestions with human correction. Quantities stay manual.'],
  [Bell, 'Smart alerts', 'Explainable alerts: what happened, the data behind it, why it matters, what to do.'],
  [Leaf, 'Sustainability dashboard', 'Measured, calculated and estimated impact kept clearly separate.'],
] as const

export function Landing() {
  return (
    <div className="min-h-screen bg-white">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
        <div className="flex items-center gap-2 font-semibold"><div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white"><Activity className="h-4 w-4" /></div>PlateSense AI</div>
        <div className="flex gap-2"><Link to="/login" className="btn-secondary">Log in</Link><Link to="/register" className="btn-primary">Register</Link></div>
      </header>
      <section className="mx-auto max-w-6xl px-4 py-16 md:py-24">
        <p className="mb-3 text-sm font-medium text-brand-700">Food management for campuses, hostels and canteens</p>
        <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-slate-900 md:text-5xl">Think Smart. Serve Right. Waste Less.</h1>
        <p className="mt-5 max-w-2xl text-lg text-slate-600">PlateSense AI connects student meal bookings, kitchen preparation, waste records and verified food redistribution so every meal is cooked from evidence instead of guesswork.</p>
        <div className="mt-8 flex gap-3"><Link to="/register" className="btn-primary px-5 py-2.5">Get started</Link><Link to="/login" className="btn-secondary px-5 py-2.5">Log in</Link></div>
      </section>
      <section className="border-t bg-slate-50 py-14">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="text-xl font-semibold">One connected platform, eight modules</h2>
          <p className="mt-1 text-sm text-slate-500">Bookings feed predictions, kitchen records feed waste analytics, waste history improves the next prediction, and surplus flows to partners.</p>
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{MODULES.map(([Icon, t, d]) => <div key={t} className="card p-5"><Icon className="mb-3 h-5 w-5 text-brand-600" /><div className="font-medium">{t}</div><p className="mt-1 text-sm text-slate-500">{d}</p></div>)}</div>
        </div>
      </section>
      <footer className="py-8 text-center text-xs text-slate-400">PlateSense AI</footer>
    </div>
  )
}

function AuthFrame({ title, sub, children }: any) {
  return <div className="flex min-h-screen items-center justify-center bg-slate-50 p-4"><div className="w-full max-w-md"><Link to="/" className="mb-6 flex items-center justify-center gap-2 font-semibold"><div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white"><Activity className="h-4 w-4" /></div>PlateSense AI</Link><div className="card p-6"><h1 className="text-xl font-semibold">{title}</h1><p className="mb-5 mt-1 text-sm text-slate-500">{sub}</p>{children}</div></div></div>
}

export function Login() {
  const { login } = useAuth()
  const [email, setEmail] = useState(''); const [pw, setPw] = useState(''); const [err, setErr] = useState(''); const { run, busy } = useAction()
  const submit = async (e: FormEvent) => { e.preventDefault(); setErr(''); try { await login(email, pw) } catch (x: any) { setErr(x.message) } }
  return (
    <AuthFrame title="Welcome back" sub="Log in to your account">
      <form onSubmit={submit} className="space-y-4">
        {err && <ErrorBox msg={err} />}
        <Field label="Email"><Input type="email" required autoComplete="username" value={email} onChange={(e: any) => setEmail(e.target.value)} /></Field>
        <Field label="Password"><Input type="password" required autoComplete="current-password" value={pw} onChange={(e: any) => setPw(e.target.value)} /></Field>
        <Btn type="submit" loading={busy} className="w-full">Log in</Btn>
        <div className="flex justify-between text-sm"><Link className="text-brand-700" to="/forgot-password">Forgot password?</Link><Link className="text-brand-700" to="/register">Create account</Link></div>
      </form>
    </AuthFrame>
  )
}

export function Register() {
  const nav = useNavigate(); const { run, busy } = useAction()
  const [role, setRole] = useState('student'); const [insts, setInsts] = useState<any[]>([]); const [f, setF] = useState<any>({ diet: 'veg' }); const [done, setDone] = useState(''); const [err, setErr] = useState('')
  useEffect(() => { api('/auth/institutions').then((d) => { setInsts(d); if (d[0]) setF((p: any) => ({ ...p, institution_id: d[0].id })) }).catch(() => {}) }, [])
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value })
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr('')
    const r = await run(() => api('/auth/register', { body: { ...f, role, institution_id: role === 'student' ? Number(f.institution_id) : undefined } }))
    if (r) { setDone(r.message); if (role === 'student') setTimeout(() => nav('/login'), 1500) }
  }
  if (done) return <AuthFrame title="You're registered" sub={done}><Link className="btn-primary w-full" to="/login">Go to login</Link></AuthFrame>
  return (
    <AuthFrame title="Create your account" sub="Students book meals; partner organisations request surplus food (approval required).">
      <div className="mb-4 grid grid-cols-2 gap-2 rounded-lg bg-slate-100 p-1 text-sm">{[['student', 'Student'], ['ngo', 'Partner / NGO']].map(([k, l]) => <button type="button" key={k} onClick={() => setRole(k)} className={`rounded-md py-1.5 font-medium ${role === k ? 'bg-white shadow-sm' : 'text-slate-500'}`}>{l}</button>)}</div>
      <form onSubmit={submit} className="space-y-3">
        <Field label="Full name"><Input required minLength={2} onChange={set('name')} /></Field>
        <Field label="Email"><Input type="email" required onChange={set('email')} /></Field>
        <Field label="Password" hint="At least 8 characters with a letter and a number"><Input type="password" required minLength={8} autoComplete="new-password" onChange={set('password')} /></Field>
        {role === 'student' ? <>
          <Field label="Institution"><Select required value={f.institution_id || ''} onChange={set('institution_id')}>{insts.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}</Select></Field>
          <div className="grid grid-cols-2 gap-3"><Field label="Diet"><Select value={f.diet} onChange={set('diet')}><option value="veg">Vegetarian</option><option value="egg">Eggetarian</option><option value="non_veg">Non-vegetarian</option><option value="vegan">Vegan</option></Select></Field><Field label="Hostel / block"><Input onChange={set('hostel')} /></Field></div>
        </> : <>
          <Field label="Organisation name"><Input required onChange={set('org_name')} /></Field>
          <Field label="Registration number" hint="Self-declared; verified manually by the mess administrator"><Input onChange={set('registration_no')} /></Field>
          <Field label="Address"><Input onChange={set('address')} /></Field>
        </>}
        <Btn type="submit" loading={busy} className="w-full">Register</Btn>
        <p className="text-center text-sm text-slate-500">Already registered? <Link className="text-brand-700" to="/login">Log in</Link></p>
      </form>
    </AuthFrame>
  )
}

export function Forgot() {
  const { run, busy } = useAction(); const [email, setEmail] = useState(''); const [msg, setMsg] = useState(''); const [token, setToken] = useState(''); const [pw, setPw] = useState(''); const [done, setDone] = useState(false)
  return (
    <AuthFrame title="Reset password" sub="Enter your email to receive a reset token.">
      {done ? <div className="space-y-3"><p className="text-sm text-emerald-700">Password updated.</p><Link to="/login" className="btn-primary w-full">Log in</Link></div> : <div className="space-y-3">
        <Field label="Email"><Input type="email" value={email} onChange={(e: any) => setEmail(e.target.value)} /></Field>
        <Btn loading={busy} className="w-full" onClick={async () => { const r = await run(() => api('/auth/forgot-password', { body: { email } })); if (r) { setMsg(r.message); if (r.dev_reset_token) setToken(r.dev_reset_token) } }}>Send reset token</Btn>
        {msg && <p className="text-sm text-slate-600">{msg} Ask your administrator for the token if email delivery is not configured (it is printed in the server log).</p>}
        {msg && <><Field label="Reset token"><Input value={token} onChange={(e: any) => setToken(e.target.value)} /></Field><Field label="New password"><Input type="password" value={pw} onChange={(e: any) => setPw(e.target.value)} /></Field>
          <Btn loading={busy} className="w-full" onClick={async () => { const r = await run(() => api('/auth/reset-password', { body: { token, new_password: pw } })); if (r) setDone(true) }}>Set new password</Btn></>}
        <Link className="block text-center text-sm text-brand-700" to="/login">Back to login</Link>
      </div>}
    </AuthFrame>
  )
}
