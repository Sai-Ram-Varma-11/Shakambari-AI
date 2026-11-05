import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, Tooltip, XAxis, YAxis, ResponsiveContainer } from 'recharts'
import { addDays, api, cap, fmtDate, fmtTime, iso, num, toLocalInput, useAction, useAuth, useFetch } from '../lib'
import { Async, AuthImage, Badge, Btn, Card, DataType, Empty, Field, Input, Modal, PageHeader, Select, Stat, Status, Table, Tabs } from '../ui'

export function Vision() {
  const list = useFetch<any[]>('/vision'); const labels = useFetch<string[]>('/vision/labels')
  const sch = useFetch<any[]>(`/menu/schedules?start=${iso(addDays(new Date(), -3))}&end=${iso(addDays(new Date(), 1))}`); const items = useFetch<any[]>('/menu/items')
  const [file, setFile] = useState<File | null>(null); const [sid, setSid] = useState(''); const [mid, setMid] = useState('')
  const [qty, setQty] = useState<any>({}); const { run, busy } = useAction()
  const upload = () => run(async () => { const f = new FormData(); f.append('file', file!); if (sid) f.append('schedule_id', sid); if (mid) f.append('menu_item_id', mid); await api('/vision/upload', { form: f }); setFile(null); list.reload() }, 'Image analysed')
  return (
    <div>
      <PageHeader title="Food waste image recognition" sub="Upload a photo of leftovers for a suggested food category. A person confirms the category and enters the weight - photos are never used to estimate weight or food safety." />
      <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">Classifier: transparent colour-histogram heuristic (no downloaded model). Treat results as suggestions; correct them where wrong. Confidence is classification confidence only.</div>
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="New observation"><div className="space-y-3">
          <Field label="Photo (JPEG, PNG or WEBP, max 5 MB)"><input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => setFile(e.target.files?.[0] || null)} className="block w-full text-sm" /></Field>
          <Field label="Meal (optional)"><Select value={sid} onChange={(e: any) => setSid(e.target.value)}><option value="">-</option>{sch.data?.map((s: any) => <option key={s.id} value={s.id}>{fmtDate(s.date)} · {cap(s.meal_type)}</option>)}</Select></Field>
          <Field label="Dish (optional)"><Select value={mid} onChange={(e: any) => setMid(e.target.value)}><option value="">-</option>{items.data?.map((i: any) => <option key={i.id} value={i.id}>{i.name}</option>)}</Select></Field>
          <Btn loading={busy} disabled={!file} onClick={upload}>Analyse image</Btn></div></Card>
        <div className="space-y-4 lg:col-span-2"><Async f={list}>{(rows) => rows.length ? rows.map((o: any) => (
          <div key={o.id} className="card flex gap-4 p-4"><AuthImage id={o.id} className="h-28 w-28 shrink-0 rounded-lg object-cover" />
            <div className="min-w-0 flex-1 space-y-2 text-sm">
              <div className="flex flex-wrap items-center gap-2"><b>{cap(o.final_label)}</b>{o.corrected_label && <Badge tone="blue">Corrected by person</Badge>}<Badge>{Math.round(o.confidence * 100)}% classification confidence</Badge><Status s={o.status} /></div>
              <div className="text-xs text-slate-500">Suggested: {cap(o.predicted_label)} · {o.width}×{o.height} {o.format}{o.quantity_kg ? ` · ${o.quantity_kg} kg (entered manually)` : ''}</div>
              {o.status === 'pending' && <div className="flex flex-wrap items-end gap-2">
                <Select className="w-40" value={o.final_label} onChange={(e: any) => run(async () => { await api(`/vision/${o.id}/correct`, { method: 'PATCH', body: { label: e.target.value } }); list.reload() })}>{labels.data?.map((l) => <option key={l} value={l}>{cap(l)}</option>)}</Select>
                <Input type="number" min="0" step="0.01" className="w-28" placeholder="Weight kg" value={qty[o.id]?.q ?? ''} onChange={(e: any) => setQty({ ...qty, [o.id]: { ...qty[o.id], q: e.target.value } })} />
                <Input type="number" min="0" step="0.01" className="w-28" placeholder="Edible kg" value={qty[o.id]?.e ?? ''} onChange={(e: any) => setQty({ ...qty, [o.id]: { ...qty[o.id], e: e.target.value } })} />
                <Btn size="sm" disabled={!qty[o.id]?.q} onClick={() => run(async () => { await api(`/vision/${o.id}/confirm`, { body: { quantity_kg: +qty[o.id].q, edible_kg: +(qty[o.id].e || 0) } }); list.reload() }, o.schedule_id && o.menu_item_id ? 'Confirmed and sent to waste analytics' : 'Confirmed')}>Confirm</Btn></div>}
              {o.status === 'pending' && !(o.schedule_id && o.menu_item_id) && <p className="text-xs text-slate-400">Link a meal and dish at upload to feed this into waste analytics.</p>}
            </div></div>)) : <Empty>No observations yet.</Empty>}</Async></div>
      </div>
    </div>
  )
}

const CHECKS = 'I have visually inspected the food, checked temperature/packaging, and confirmed safe transport arrangements.'

export function Surplus() {
  const { user } = useAuth(); const isMgr = user.role !== 'kitchen'
  const [tab, setTab] = useState('listings')
  const list = useFetch<any[]>('/surplus'); const reqs = useFetch<any[]>('/surplus/requests/all'); const sug = useFetch<any[]>('/surplus/suggestions'); const hist = useFetch<any[]>(isMgr ? '/surplus/donations/history' : null)
  const { run, busy } = useAction(); const [show, setShow] = useState(false); const [rev, setRev] = useState<any>(null); const [ok, setOk] = useState(false); const [notes, setNotes] = useState('')
  const blank = { food_name: '', diet: 'veg', ingredients: '', category: 'cooked', quantity_kg: '', portions: '', prepared_at: toLocalInput(addDays(new Date(), 0)), storage_condition: 'hot_held', storage_temp_c: '', use_by: '' }
  const [f, setF] = useState<any>(blank); const [res, setRes] = useState<any>(null)
  const submit = async () => { const r = await run(() => api('/surplus', { body: { ...f, ingredients: f.ingredients.split(',').map((i: string) => i.trim()).filter(Boolean), quantity_kg: +f.quantity_kg, portions: +(f.portions || 0), storage_temp_c: f.storage_temp_c === '' ? null : +f.storage_temp_c, use_by: f.use_by || null } })); if (r) { setRes(r); list.reload(); sug.reload() } }
  const reload = () => { list.reload(); reqs.reload(); hist.reload() }
  return (
    <div>
      <PageHeader title="Surplus food & redistribution" sub="Surplus is listed only after automatic screening AND human food-safety review. Nothing is declared safe automatically." action={<Btn onClick={() => { setShow(true); setRes(null) }}>List surplus</Btn>} />
      <Tabs tabs={[['listings', 'Listings'], ['requests', 'Collection requests'], ['suggestions', 'From kitchen records'], ...(isMgr ? [['history', 'Donation history']] : [])] as any} value={tab} onChange={setTab} />
      {tab === 'listings' && <Card><Async f={list}>{(rows) => <Table rows={rows} empty="No listings yet." cols={[{ h: 'Food', r: (r) => <div><b>{r.food_name}</b><div className="text-xs text-slate-500">{r.diet === 'vegan' ? 'Vegan' : 'Lacto-vegetarian'} · {cap(r.category)} · {cap(r.storage_condition)}{r.storage_temp_c !== null ? ` ${r.storage_temp_c}°C` : ''}</div></div> }, { h: 'Qty', r: (r) => `${r.quantity_kg} kg / ${r.portions} portions` }, { h: 'Prepared', r: (r) => fmtTime(r.prepared_at) }, { h: 'Use by', r: (r) => r.use_by ? fmtTime(r.use_by) : '-' }, { h: 'Status', r: (r) => <Status s={r.status} /> }, { h: 'Screening', r: (r) => <details><summary className="cursor-pointer text-xs text-brand-700">{r.auto_check?.every((c: any) => c.passed) ? 'All passed' : 'Failed'}</summary><ul className="mt-1 space-y-0.5 text-xs">{r.auto_check?.map((c: any, i: number) => <li key={i} className={c.passed ? 'text-emerald-700' : 'text-rose-700'}>{c.passed ? '✓' : '✗'} {c.rule}: {c.detail}</li>)}</ul></details> },
        { h: '', r: (r) => isMgr && <div className="flex gap-1">{r.status === 'pending_review' && <Btn size="sm" onClick={() => { setRev(r); setOk(false); setNotes('') }}>Review</Btn>}{['eligible', 'pending_review'].includes(r.status) && <Btn size="sm" variant="secondary" onClick={() => run(async () => { await api(`/surplus/${r.id}/withdraw`, { method: 'POST' }); reload() }, 'Withdrawn')}>Withdraw</Btn>}</div> }]} />}</Async></Card>}
      {tab === 'requests' && <Card><Async f={reqs}>{(rows) => <Table rows={rows} empty="No requests yet." cols={[{ h: 'Partner', r: (r) => r.org_name }, { h: 'Food', r: (r) => `${r.food_name} (${r.quantity_kg} kg)` }, { h: 'Message', r: (r) => r.message || '-' }, { h: 'Status', r: (r) => <Status s={r.status} /> }, { h: 'Pickup', r: (r) => r.pickup_time ? fmtTime(r.pickup_time) : '-' }, { h: 'Collected', r: (r) => r.collected_kg ? `${r.collected_kg} kg` : '-' },
        { h: '', r: (r) => isMgr && r.status === 'pending' && <div className="flex gap-1"><Btn size="sm" onClick={() => run(async () => { await api(`/surplus/requests/${r.id}/decision`, { body: { approve: true, pickup_time: toLocalInput(new Date(Date.now() + 3600e3)) } }); reload() }, 'Approved - pickup in 1 hour')}>Approve</Btn><Btn size="sm" variant="secondary" onClick={() => run(async () => { await api(`/surplus/requests/${r.id}/decision`, { body: { approve: false } }); reload() }, 'Rejected')}>Reject</Btn></div> }]} />}</Async></Card>}
      {tab === 'suggestions' && <Card title="Edible leftovers recorded by the kitchen (not yet listed)"><Async f={sug}>{(rows) => <Table rows={rows.map((r: any, i: number) => ({ id: i, ...r }))} empty="Nothing to suggest right now." cols={[{ h: 'Dish', r: (r) => r.food_name }, { h: 'Meal', r: (r) => `${fmtDate(r.date)} · ${cap(r.meal_type)}` }, { h: 'Edible', r: (r) => `${r.edible_kg} kg` }, { h: '', r: (r) => <Btn size="sm" variant="secondary" onClick={() => { setF({ ...blank, food_name: r.food_name, diet: r.diet, ingredients: (r.ingredients || []).join(', '), quantity_kg: r.edible_kg, portions: r.suggested_portions, schedule_id: r.schedule_id, menu_item_id: r.menu_item_id }); setRes(null); setShow(true) }}>Prepare listing</Btn> }]} />}</Async><p className="mt-3 text-xs text-slate-500">Prefilled from approved vegetarian kitchen records. Confirm ingredients, preparation time and holding temperature before submitting.</p></Card>}
      {tab === 'history' && <Card><Async f={hist}>{(rows) => <Table rows={rows} empty="No collections yet." cols={[{ h: 'When', r: (r) => fmtTime(r.collected_at) }, { h: 'Food', r: (r) => r.food_name }, { h: 'Partner', r: (r) => r.org_name }, { h: 'Collected', r: (r) => `${r.collected_kg} kg` }, { h: 'Portions', r: (r) => r.portions }, { h: 'Status', r: (r) => <Status s={r.status} /> }]} />}</Async></Card>}

      <Modal open={show} onClose={() => setShow(false)} title="List surplus food">
        {res ? <div className="space-y-3 text-sm"><Status s={res.status} /><ul className="space-y-1 text-xs">{res.auto_check.map((c: any, i: number) => <li key={i} className={c.passed ? 'text-emerald-700' : 'text-rose-700'}>{c.passed ? '✓' : '✗'} {c.rule}: {c.detail}</li>)}</ul><p className="text-xs text-slate-500">{res.status === 'pending_review' ? 'Passed screening. A mess administrator must now complete the food-safety review before partners can see it.' : 'Failed screening - this food cannot be offered. Check the details above.'}</p><Btn onClick={() => setShow(false)}>Close</Btn></div> :
          <div className="space-y-3"><Field label="Food"><Input value={f.food_name} onChange={(e: any) => setF({ ...f, food_name: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-3"><Field label="Diet"><Select value={f.diet} onChange={(e: any) => setF({ ...f, diet: e.target.value })}><option value="veg">Lacto-vegetarian</option><option value="vegan">Vegan</option></Select></Field><Field label="Ingredients (comma-separated)" hint="Animal products, meat, fish, seafood and eggs are not allowed"><Input required value={f.ingredients} onChange={(e: any) => setF({ ...f, ingredients: e.target.value })} placeholder="e.g. lentils, tomato, spices" /></Field></div>
            <div className="grid grid-cols-3 gap-3"><Field label="Category"><Select value={f.category} onChange={(e: any) => setF({ ...f, category: e.target.value })}>{['cooked', 'packaged', 'fruit', 'bakery', 'raw', 'other'].map((c) => <option key={c}>{c}</option>)}</Select></Field><Field label="Quantity kg"><Input type="number" min="0" step="0.1" value={f.quantity_kg} onChange={(e: any) => setF({ ...f, quantity_kg: e.target.value })} /></Field><Field label="Portions"><Input type="number" min="0" value={f.portions} onChange={(e: any) => setF({ ...f, portions: e.target.value })} /></Field></div>
            <Field label="Prepared at"><Input type="datetime-local" value={f.prepared_at} onChange={(e: any) => setF({ ...f, prepared_at: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-3"><Field label="Storage"><Select value={f.storage_condition} onChange={(e: any) => setF({ ...f, storage_condition: e.target.value })}>{['hot_held', 'refrigerated', 'room_temp', 'frozen'].map((c) => <option key={c} value={c}>{cap(c)}</option>)}</Select></Field><Field label="Measured temp °C"><Input type="number" step="0.5" value={f.storage_temp_c} onChange={(e: any) => setF({ ...f, storage_temp_c: e.target.value })} /></Field></div>
            <Field label="Use by (optional)"><Input type="datetime-local" value={f.use_by} onChange={(e: any) => setF({ ...f, use_by: e.target.value })} /></Field>
            <Btn loading={busy} disabled={!f.food_name || !f.ingredients || !f.quantity_kg} onClick={submit}>Screen & submit for review</Btn></div>}
      </Modal>
      <Modal open={!!rev} onClose={() => setRev(null)} title={`Food-safety review: ${rev?.food_name}`}>
        <div className="space-y-3 text-sm"><ul className="space-y-1 text-xs">{rev?.auto_check?.map((c: any, i: number) => <li key={i} className={c.passed ? 'text-emerald-700' : 'text-rose-700'}>{c.passed ? '✓' : '✗'} {c.rule}: {c.detail}</li>)}</ul>
          <label className="flex gap-2 rounded-lg border p-3 text-sm"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} /><span>{CHECKS}</span></label>
          <Field label="Review notes"><Input value={notes} onChange={(e: any) => setNotes(e.target.value)} /></Field>
          <div className="flex gap-2"><Btn disabled={!ok} loading={busy} onClick={async () => { const r = await run(() => api(`/surplus/${rev.id}/review`, { body: { decision: 'approve', checklist_confirmed: ok, notes } }), 'Approved - partners notified'); if (r) { setRev(null); reload() } }}>Approve as eligible</Btn><Btn variant="danger" loading={busy} onClick={async () => { await run(() => api(`/surplus/${rev.id}/review`, { body: { decision: 'reject', notes } }), 'Rejected'); setRev(null); reload() }}>Reject</Btn></div></div>
      </Modal>
    </div>
  )
}

export function Partner() {
  const { user } = useAuth(); const [tab, setTab] = useState('available')
  const avail = useFetch<any[]>('/surplus'); const mine = useFetch<any[]>('/surplus/requests/all'); const hist = useFetch<any[]>('/surplus/donations/history')
  const { run, busy } = useAction(); const [q, setQ] = useState<any>({})
  const reload = () => { avail.reload(); mine.reload(); hist.reload() }
  const total = hist.data?.reduce((a: number, h: any) => a + h.collected_kg, 0) || 0
  return (
    <div>
      <PageHeader title={user.partner?.org_name || 'Partner dashboard'} sub="Request verified surplus food, confirm collection and track deliveries." />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4"><Stat label="Available now" value={avail.data?.length ?? '-'} /><Stat label="Open requests" value={mine.data?.filter((r: any) => ['pending', 'approved', 'picked_up'].includes(r.status)).length ?? '-'} /><Stat label="Collected to date" value={`${num(total)} kg`} sub="As recorded at pickup" /></div>
      <Tabs tabs={[['available', 'Available surplus'], ['requests', 'My requests'], ['history', 'Donation history']]} value={tab} onChange={setTab} />
      {tab === 'available' && <Async f={avail}>{(rows) => rows.length ? <div className="grid gap-4 md:grid-cols-2">{rows.map((r: any) => <div key={r.id} className="card p-4"><div className="flex justify-between"><b>{r.food_name}</b><Status s={r.status} /></div><div className="mt-1 text-sm text-slate-600">{r.quantity_kg} kg · about {r.portions} portions</div><div className="text-xs text-slate-500">Prepared {fmtTime(r.prepared_at)} · {cap(r.storage_condition)}{r.use_by ? ` · use by ${fmtTime(r.use_by)}` : ''}</div><p className="mt-2 text-xs text-slate-400">Verified by the institution's staff at listing time. You remain responsible for safe transport and prompt distribution.</p><Btn className="mt-3" size="sm" loading={busy} onClick={() => run(async () => { await api(`/surplus/${r.id}/request`, { body: {} }); reload() }, 'Request sent')}>Request collection</Btn></div>)}</div> : <Empty>No eligible surplus right now. You'll be notified when new food is listed.</Empty>}</Async>}
      {tab === 'requests' && <Card><Async f={mine}>{(rows) => <Table rows={rows} empty="No requests yet." cols={[{ h: 'Food', r: (r) => `${r.food_name} (${r.quantity_kg} kg)` }, { h: 'Status', r: (r) => <Status s={r.status} /> }, { h: 'Pickup', r: (r) => r.pickup_time ? fmtTime(r.pickup_time) : '-' },
        { h: 'Update', r: (r) => r.status === 'approved' ? <div className="flex items-center gap-1"><Input type="number" min="0" step="0.1" className="w-24" placeholder="kg" value={q[r.id]?.kg ?? ''} onChange={(e: any) => setQ({ ...q, [r.id]: { ...q[r.id], kg: e.target.value } })} /><Input type="number" min="0" className="w-24" placeholder="portions" value={q[r.id]?.p ?? ''} onChange={(e: any) => setQ({ ...q, [r.id]: { ...q[r.id], p: e.target.value } })} /><Btn size="sm" disabled={!q[r.id]?.kg} onClick={() => run(async () => { await api(`/surplus/requests/${r.id}/status`, { body: { status: 'picked_up', collected_kg: +q[r.id].kg, portions: +(q[r.id].p || 0) } }); reload() }, 'Marked picked up')}>Picked up</Btn><Btn size="sm" variant="secondary" onClick={() => run(async () => { await api(`/surplus/requests/${r.id}/status`, { body: { status: 'cancelled' } }); reload() })}>Cancel</Btn></div> : r.status === 'picked_up' ? <Btn size="sm" onClick={() => run(async () => { await api(`/surplus/requests/${r.id}/status`, { body: { status: 'delivered', delivered_to: 'Beneficiaries' } }); reload() }, 'Marked delivered')}>Mark delivered</Btn> : '-' }]} />}</Async></Card>}
      {tab === 'history' && <Card><Async f={hist}>{(rows) => <Table rows={rows} empty="No donations yet." cols={[{ h: 'When', r: (r) => fmtTime(r.collected_at) }, { h: 'Food', r: (r) => r.food_name }, { h: 'Collected', r: (r) => `${r.collected_kg} kg` }, { h: 'Portions', r: (r) => r.portions }, { h: 'Delivered to', r: (r) => r.delivered_to || '-' }, { h: 'Status', r: (r) => <Status s={r.status} /> }]} />}</Async></Card>}
    </div>
  )
}

export function Alerts() {
  const { user } = useAuth(); const a = useFetch<any[]>('/alerts'); const { run, busy } = useAction(); const isMgr = user.role !== 'kitchen'
  return (
    <div>
      <PageHeader title="Smart alerts" sub="Rule-based and statistical alerts. Each shows what happened, the data behind it, why it matters and what to consider." action={isMgr && <Btn loading={busy} onClick={() => run(async () => { await api('/alerts/generate', { method: 'POST' }); a.reload() }, 'Alerts refreshed')}>Refresh alerts</Btn>} />
      <Async f={a}>{(rows) => rows.length ? <div className="space-y-4">{rows.map((x: any) => <div key={x.id} className="card p-4"><div className="mb-2 flex items-center justify-between"><div className="flex items-center gap-2"><Status s={x.severity} /><h3 className="font-medium">{x.title}</h3></div>{isMgr && <Btn size="sm" variant="secondary" onClick={() => run(async () => { await api(`/alerts/${x.id}/resolve`, { method: 'POST' }); a.reload() })}>Resolve</Btn>}</div>
        <dl className="grid gap-3 text-sm md:grid-cols-2"><div><dt className="label">What happened</dt><dd>{x.what}</dd></div><div><dt className="label">Supporting data</dt><dd>{x.evidence}</dd></div><div><dt className="label">Why it matters</dt><dd>{x.why}</dd></div><div><dt className="label">Consider</dt><dd>{x.action}</dd></div></dl></div>)}</div> : <Empty>No open alerts.{isMgr && ' Use "Refresh alerts" to analyse the latest data.'}</Empty>}</Async>
    </div>
  )
}

export function Sustainability() {
  const { user } = useAuth(); const [start, setStart] = useState(iso(addDays(new Date(), -89))); const [end, setEnd] = useState(iso(new Date()))
  const s = useFetch<any>(`/sustainability/summary?start=${start}&end=${end}`)
  const [period, setPeriod] = useState(iso(new Date()).slice(0, 7)); const rep = useFetch<any>(user.role === 'mess_admin' || user.role === 'super_admin' ? `/sustainability/report?period=${period}` : null)
  const { run } = useAction()
  const fmt = (m: any) => `${num(m.value, m.unit === '%' ? 1 : m.unit === 'INR' ? 0 : 1)} ${m.unit}`
  return (
    <div>
      <PageHeader title="Sustainability impact" sub="Measured values are recorded directly, calculated values are derived from them, and estimates depend on stated assumptions." />
      <div className="mb-4 flex flex-wrap gap-3"><Field label="From"><Input type="date" value={start} onChange={(e: any) => setStart(e.target.value)} /></Field><Field label="To"><Input type="date" value={end} onChange={(e: any) => setEnd(e.target.value)} /></Field></div>
      <Async f={s}>{(d) => <div className="space-y-6">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">{d.metrics.map((m: any) => <div key={m.key} className="card p-4"><div className="flex items-center justify-between"><span className="text-xs font-medium uppercase tracking-wide text-slate-500">{m.label}</span><DataType t={m.type} /></div><div className="mt-1 text-xl font-semibold">{fmt(m)}</div><div className="mt-1 text-xs text-slate-400">{m.note}</div></div>)}</div>
        <Card title="Performance summary"><ul className="list-disc space-y-1 pl-5 text-sm">{d.summary.map((l: string, i: number) => <li key={i}>{l}</li>)}</ul></Card>
        <Card title="Monthly food flow (kg)">{d.series.length ? <ResponsiveContainer width="100%" height={280}><BarChart data={d.series} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}><CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="period" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Legend /><Bar dataKey="consumed" fill="#10b981" name="Consumed" /><Bar dataKey="leftover" fill="#f59e0b" name="Leftover" /><Bar dataKey="collected" fill="#0ea5e9" name="Collected by partners" /></BarChart></ResponsiveContainer> : <Empty>No recorded data in this range.</Empty>}</Card></div>}</Async>
      {rep.data !== null || rep.loading ? <Card className="mt-6" title="Monthly / yearly report" action={<div className="flex gap-2"><Input className="w-32" value={period} onChange={(e: any) => setPeriod(e.target.value)} placeholder="YYYY-MM or YYYY" /><Btn size="sm" variant="secondary" onClick={() => run(async () => { await api(`/sustainability/snapshot?period=${period}`, { method: 'POST' }) }, 'Snapshot saved')}>Save snapshot</Btn></div>}><Async f={rep}>{(d) => <><ul className="mb-3 list-disc space-y-1 pl-5 text-sm">{d.summary.map((l: string, i: number) => <li key={i}>{l}</li>)}</ul><Table rows={d.metrics.map((m: any) => ({ id: m.key, ...m }))} cols={[{ h: 'Metric', r: (m) => m.label }, { h: 'Value', r: (m) => fmt(m), cls: 'text-right' }, { h: 'Type', r: (m) => <DataType t={m.type} /> }]} /></>}</Async></Card> : null}
    </div>
  )
}
