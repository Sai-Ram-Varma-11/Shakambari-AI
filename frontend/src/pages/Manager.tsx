import { Fragment, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { BrainCircuit, RefreshCw, Upload } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { addDays, api, cap, fmtDate, iso, num, useAction, useAuth, useFetch, MEALS } from '../lib'
import { Async, Badge, Btn, Card, Empty, Field, Input, PageHeader, Select, Stat, Status, Table, Tabs } from '../ui'

const chartProps = { margin: { top: 5, right: 10, left: 0, bottom: 0 } }

export function ManagerDashboard() {
  const { user } = useAuth(); const isMgr = user.role !== 'kitchen'
  const start = iso(addDays(new Date(), -29))
  const waste = useFetch<any>(`/waste/summary?start=${start}&group=day`)
  const pred = useFetch<any[]>('/predict/upcoming?days=1')
  const alerts = useFetch<any[]>('/alerts')
  const reqs = useFetch<any[]>('/surplus/requests/all?status=pending')
  const part = useFetch<any[]>(isMgr ? '/bookings/participation?days=30' : null)
  return (
    <div>
      <PageHeader title="Operations dashboard" sub="Live view across bookings, predictions, waste and redistribution." />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Async f={waste}>{(w) => <><Stat label="Waste rate (30 d)" value={`${num(w.totals.waste_pct)}%`} sub={`${num(w.totals.leftover)} kg of ${num(w.totals.prepared)} kg prepared`} tone={w.totals.waste_pct > 15 ? 'warn' : 'good'} /><Stat label="Cost of leftovers (30 d)" value={`${w.currency} ${num(w.totals.loss, 0)}`} sub="Calculated: leftover kg × cost/kg" /></>}</Async>
        <Stat label="Open alerts" value={alerts.data?.length ?? '-'} sub={<Link className="text-brand-700" to="/alerts">View alerts</Link>} tone={alerts.data?.length ? 'warn' : 'good'} />
        <Stat label="Requests awaiting decision" value={reqs.data?.length ?? '-'} sub={<Link className="text-brand-700" to="/surplus">Open surplus</Link>} />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Waste rate trend (last 30 days)"><Async f={waste}>{(w) => w.series.length ? <ResponsiveContainer width="100%" height={240}><LineChart data={w.series} {...chartProps}><CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="period" tick={{ fontSize: 11 }} /><YAxis unit="%" tick={{ fontSize: 11 }} /><Tooltip /><Line dataKey="waste_pct" name="Waste %" stroke="#059669" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer> : <Empty>No waste records in this period.</Empty>}</Async></Card>
        <Card title="Next meals - predicted demand" action={<Link to="/prediction" className="text-xs text-brand-700">Details</Link>}><Async f={pred}>{(p) => <Table rows={p.slice(0, 8)} empty="No upcoming meals." cols={[{ h: 'Meal', r: (r) => `${fmtDate(r.date)} · ${cap(r.meal_type)}` }, { h: 'Booked', r: (r) => r.active_bookings, cls: 'text-right' }, { h: 'Predicted', r: (r) => <b>{r.predicted_attendance}</b>, cls: 'text-right' }, { h: 'Range', r: (r) => `${r.lower}-${r.upper}`, cls: 'text-right' }, { h: 'Confidence', r: (r) => <Status s={r.confidence} /> }]} />}</Async></Card>
        <Card title="Top alerts"><Async f={alerts}>{(a) => a.length ? <ul className="space-y-3">{a.slice(0, 4).map((x) => <li key={x.id} className="flex gap-2 text-sm"><Status s={x.severity} /><div><div className="font-medium">{x.title}</div><div className="text-xs text-slate-500">{x.what}</div></div></li>)}</ul> : <Empty>No open alerts. Generate alerts from the Smart alerts page.</Empty>}</Async></Card>
        {isMgr && <Card title="Bookings vs attendance (30 d, recorded meals)"><Async f={part}>{(rows) => <Table rows={rows} empty="No attendance recorded yet." cols={[{ h: 'Meal', r: (r) => cap(r.meal_type) }, { h: 'Avg booked', r: (r) => r.avg_active_bookings, cls: 'text-right' }, { h: 'Avg attended', r: (r) => r.avg_attendance, cls: 'text-right' }, { h: 'Attendance per booking', r: (r) => r.attendance_per_booking, cls: 'text-right' }]} />}</Async></Card>}
      </div>
    </div>
  )
}

export function Prediction() {
  const { user } = useAuth(); const isMgr = user.role !== 'kitchen'
  const [days, setDays] = useState(3); const [open, setOpen] = useState<number | null>(null)
  const pred = useFetch<any[]>(`/predict/upcoming?days=${days}`)
  const hist = useFetch<any>(isMgr ? '/predict/history' : null)
  const { run, busy } = useAction()
  const save = () => run(async () => { await api('/predict/run', { body: { days } }); hist.reload() }, 'Predictions saved and team notified')
  return (
    <div>
      <PageHeader title="Demand prediction" sub="Expected attendance and recommended preparation quantities, combining bookings, history and the calendar." action={<div className="flex gap-2"><Select value={days} onChange={(e: any) => setDays(+e.target.value)} className="w-36">{[1, 2, 3, 5, 7].map((d) => <option key={d} value={d}>Next {d} day{d > 1 ? 's' : ''}</option>)}</Select><Btn loading={busy} onClick={save}>Save & notify team</Btn></div>} />
      <Card title="Upcoming meals">
        <Async f={pred}>{(rows) => rows.length ? <div className="overflow-x-auto"><table className="tbl"><thead><tr><th>Meal</th><th className="text-right">Active bookings</th><th className="text-right">Cancelled</th><th className="text-right">Predicted attendance</th><th className="text-right">80% range</th><th>Confidence</th><th /></tr></thead><tbody>
          {rows.map((r: any) => <Fragment key={r.schedule_id}><tr><td>{fmtDate(r.date)} · {cap(r.meal_type)}</td><td className="text-right">{r.active_bookings}</td><td className="text-right">{r.cancellations}</td><td className="text-right font-semibold">{r.predicted_attendance}</td><td className="text-right">{r.lower}-{r.upper}</td><td><Status s={r.confidence} /></td><td><Btn size="sm" variant="secondary" onClick={() => setOpen(open === r.schedule_id ? null : r.schedule_id)}>{open === r.schedule_id ? 'Hide' : 'Dishes'}</Btn></td></tr>
            {open === r.schedule_id && <tr><td colSpan={7} className="bg-slate-50"><Table rows={r.dishes} cols={[{ h: 'Dish', r: (d) => d.name }, { h: 'Recommended (kg)', r: (d) => <b>{d.recommended_kg}</b>, cls: 'text-right' }, { h: 'Range (kg)', r: (d) => `${d.lower_kg}-${d.upper_kg}`, cls: 'text-right' }, { h: 'Uptake', r: (d) => d.uptake_source === 'history' ? `${Math.round(d.uptake * 100)}% (n=${d.uptake_n})` : <Badge tone="amber">default assumption</Badge> }, { h: 'Prepared (kg)', r: (d) => num(d.prepared_kg), cls: 'text-right' }, { h: 'Check', r: (d) => d.status ? <Status s={d.status} /> : '-' }]} />
              <p className="px-3 pb-2 text-xs text-slate-500">Recommended = predicted attendance × portion × historical uptake × (1 + buffer). Historical bookings-to-attendance ratio: {r.historical_attendance_per_booking} attendees per booking, so unbooked attendance is included.</p></td></tr>}</Fragment>)}</tbody></table></div> : <Empty>No meals scheduled in this window.</Empty>}</Async>
      </Card>
      {isMgr && <Card className="mt-6" title="Saved predictions vs actual attendance"><Async f={hist}>{(h) => <><p className="mb-3 text-sm text-slate-500">{h.compared ? `Mean absolute error on ${h.compared} stored predictions with recorded attendance: ${h.mae_on_stored_predictions} students.` : 'Compared once attendance is recorded for predicted meals.'}</p><Table rows={h.rows.slice(0, 15)} cols={[{ h: 'Meal', r: (r) => `${fmtDate(r.date)} · ${cap(r.meal_type)}` }, { h: 'Booked', r: (r) => r.active_bookings, cls: 'text-right' }, { h: 'Predicted', r: (r) => r.predicted, cls: 'text-right' }, { h: 'Actual', r: (r) => r.actual ?? '-', cls: 'text-right' }]} /></>}</Async></Card>}
    </div>
  )
}

export function Preparation() {
  const { user } = useAuth()
  const list = useFetch<any[]>(`/menu/schedules?start=${iso(addDays(new Date(), -3))}&end=${iso(addDays(new Date(), 3))}`)
  const [sid, setSid] = useState<number | null>(null)
  const plan = useFetch<any>(sid ? `/kitchen/plan/${sid}` : null)
  const [rows, setRows] = useState<any>({}); const [head, setHead] = useState(''); const [email, setEmail] = useState(''); const [note, setNote] = useState('')
  const { run, busy } = useAction()
  useEffect(() => { if (!sid && list.data?.length) { const t = iso(new Date()); setSid((list.data.find((s: any) => s.date === t && s.meal_type === 'lunch') || list.data[0]).id) } }, [list.data])
  useEffect(() => { if (plan.data) { const r: any = {}; plan.data.dishes.forEach((d: any) => (r[d.menu_item_id] = { prepared: d.prepared_kg ?? '', available: d.available_kg ?? '', consumed: d.consumed_kg ?? '', leftover: d.leftover_kg ?? '', edible: d.edible_kg ?? '' })); setRows(r); setHead(plan.data.headcount ?? '') } }, [plan.data])
  const set = (id: number, k: string, v: string) => setRows({ ...rows, [id]: { ...rows[id], [k]: v } })
  const nn = (v: any) => (v === '' || v === undefined ? null : Number(v))
  const savePrep = () => run(async () => { await api('/kitchen/preparation', { body: { schedule_id: sid, items: Object.entries(rows).filter(([, r]: any) => r.prepared !== '').map(([id, r]: any) => ({ menu_item_id: +id, prepared_qty: +r.prepared, available_qty: nn(r.available) })) } }); plan.reload() }, 'Preparation saved')
  const saveOut = () => run(async () => { await api('/kitchen/outcome', { body: { schedule_id: sid, items: Object.entries(rows).filter(([, r]: any) => r.consumed !== '' && r.leftover !== '').map(([id, r]: any) => ({ menu_item_id: +id, consumed_qty: +r.consumed, leftover_qty: +r.leftover, edible_qty: +(r.edible || 0) })) } }); plan.reload() }, 'Consumption and leftovers saved')
  const cur = list.data?.find((s: any) => s.id === sid)
  const inp = (id: number, k: string, w = 'w-24') => <Input type="number" min="0" step="0.01" className={w} value={rows[id]?.[k] ?? ''} onChange={(e: any) => set(id, k, e.target.value)} aria-label={k} />
  return (
    <div>
      <PageHeader title="Food preparation" sub="Follow the recommendation, record what was cooked, then record consumption and leftovers. All quantities are in kg of cooked food." />
      <div className="mb-4 max-w-md"><Field label="Meal"><Select value={sid ?? ''} onChange={(e: any) => setSid(+e.target.value)}>{list.data?.map((s: any) => <option key={s.id} value={s.id}>{fmtDate(s.date)} · {cap(s.meal_type)} ({s.active_bookings} booked)</option>)}</Select></Field></div>
      <Async f={plan}>{(p) => <div className="space-y-6">
        <Card title={<>Quantities <Status s={p.service_status} /></>} action={<div className="flex gap-2"><Btn size="sm" variant="secondary" loading={busy} onClick={savePrep}>Save preparation</Btn><Btn size="sm" loading={busy} onClick={saveOut}>Save consumption & leftovers</Btn></div>}>
          <div className="overflow-x-auto"><table className="tbl"><thead><tr><th>Dish</th><th className="text-right">Recommended</th><th>Prepared</th><th>Available</th><th>Consumed</th><th>Leftover</th><th>Edible leftover</th></tr></thead><tbody>
            {p.dishes.map((d: any) => <tr key={d.menu_item_id}><td className="font-medium">{d.name}</td><td className="text-right">{d.recommended_kg ? <b className="text-brand-700">{d.recommended_kg}</b> : <span className="text-xs text-slate-400">run prediction</span>}</td><td>{inp(d.menu_item_id, 'prepared')}</td><td>{inp(d.menu_item_id, 'available')}</td><td>{inp(d.menu_item_id, 'consumed')}</td><td>{inp(d.menu_item_id, 'leftover')}</td><td>{inp(d.menu_item_id, 'edible')}</td></tr>)}</tbody></table></div>
          <p className="mt-3 text-xs text-slate-500">Edible leftover is the part that is still good food and may be offered for redistribution after human review. Leftover minus edible is recorded as inedible waste.</p>
        </Card>
        <div className="grid gap-6 md:grid-cols-2">
          <Card title="Attendance">
            <div className="space-y-3"><div className="flex items-end gap-2"><Field label="Total headcount served"><Input type="number" min="0" value={head} onChange={(e: any) => setHead(e.target.value)} /></Field><Btn variant="secondary" loading={busy} onClick={() => run(async () => { await api(`/attendance/${sid}/headcount`, { body: { headcount: +head } }); plan.reload() }, 'Headcount saved')}>Save</Btn></div>
              <div className="flex items-end gap-2"><Field label="Mark a student present (email)"><Input value={email} onChange={(e: any) => setEmail(e.target.value)} placeholder="student@college.edu" /></Field><Btn variant="secondary" loading={busy} onClick={() => run(async () => { const r = await api(`/attendance/${sid}/mark`, { body: { student_email: email } }); setEmail(''); setHead(r.headcount); plan.reload() }, 'Attendance marked')}>Mark</Btn></div>
              <p className="text-xs text-slate-500">Headcount is the figure used to train the forecast. Marking individual students also records whether they had booked.</p></div>
          </Card>
          <Card title="Meal status & observations">
            <div className="space-y-3"><div className="flex gap-2">{['planned', 'preparing', 'served', 'closed'].map((s) => <Btn key={s} size="sm" variant={p.service_status === s ? 'primary' : 'secondary'} onClick={() => run(async () => { await api(`/menu/schedules/${sid}/status`, { method: 'PATCH', body: { service_status: s } }); plan.reload() }, 'Status updated')}>{cap(s)}</Btn>)}</div>
              <Field label="Waste observation (notifies the manager)"><Input value={note} onChange={(e: any) => setNote(e.target.value)} placeholder="e.g. Sambar returned mostly untouched" /></Field>
              <Btn variant="secondary" disabled={note.length < 3} loading={busy} onClick={() => run(async () => { await api('/kitchen/observation', { body: { schedule_id: sid, note } }); setNote('') }, 'Observation sent')}>Send observation</Btn></div>
          </Card>
        </div></div>}</Async>
    </div>
  )
}

const download = async (path: string, name: string) => { const b: Blob = await api(path, { raw: true }); const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = name; a.click() }

export function WasteAnalytics() {
  const { user } = useAuth(); const isMgr = user.role !== 'kitchen'
  const [start, setStart] = useState(iso(addDays(new Date(), -29))); const [end, setEnd] = useState(iso(new Date())); const [group, setGroup] = useState('day')
  const q = `start=${start}&end=${end}`
  const sum = useFetch<any>(`/waste/summary?${q}&group=${group}`); const dish = useFetch<any[]>(`/waste/by-dish?${q}`); const meal = useFetch<any[]>(`/waste/by-meal?${q}`)
  return (
    <div>
      <PageHeader title="Food waste analytics" sub="Computed from kitchen records: prepared, consumed and leftover quantities." action={isMgr && <Btn variant="secondary" onClick={() => download(`/waste/export.csv?${q}`, 'waste_report.csv')}>Export CSV</Btn>} />
      <div className="mb-4 flex flex-wrap gap-3"><Field label="From"><Input type="date" value={start} onChange={(e: any) => setStart(e.target.value)} /></Field><Field label="To"><Input type="date" value={end} onChange={(e: any) => setEnd(e.target.value)} /></Field><Field label="Group by"><Select value={group} onChange={(e: any) => setGroup(e.target.value)}>{['day', 'week', 'month', 'year'].map((g) => <option key={g} value={g}>{cap(g)}</option>)}</Select></Field></div>
      <Async f={sum}>{(s) => { const t = s.totals; return <><div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-6"><Stat label="Prepared" value={`${num(t.prepared)} kg`} /><Stat label="Consumed" value={`${num(t.consumed)} kg`} sub={`${num(t.consumption_pct)}%`} /><Stat label="Leftover" value={`${num(t.leftover)} kg`} sub={`${num(t.waste_pct)}% waste`} tone={t.waste_pct > 15 ? 'warn' : 'good'} /><Stat label="Edible surplus" value={`${num(t.edible)} kg`} /><Stat label="Inedible waste" value={`${num(t.inedible)} kg`} /><Stat label="Est. loss" value={`${s.currency} ${num(t.loss, 0)}`} /></div>
        <Card title="Prepared vs consumed vs leftover" className="mb-6">{s.series.length ? <ResponsiveContainer width="100%" height={280}><BarChart data={s.series} {...chartProps}><CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="period" tick={{ fontSize: 10 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Legend /><Bar dataKey="consumed" stackId="a" fill="#10b981" name="Consumed kg" /><Bar dataKey="leftover" stackId="a" fill="#f59e0b" name="Leftover kg" /></BarChart></ResponsiveContainer> : <Empty>No records in this range.</Empty>}</Card></> }}</Async>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="By dish (most leftover first)"><Async f={dish}>{(rows) => <Table rows={rows.slice(0, 12)} cols={[{ h: 'Dish', r: (r) => r.item }, { h: 'Prepared', r: (r) => num(r.prepared), cls: 'text-right' }, { h: 'Leftover', r: (r) => num(r.leftover), cls: 'text-right' }, { h: 'Waste %', r: (r) => <Badge tone={r.waste_pct > 20 ? 'red' : r.waste_pct > 10 ? 'amber' : 'green'}>{num(r.waste_pct)}%</Badge>, cls: 'text-right' }, { h: 'Loss', r: (r) => num(r.loss, 0), cls: 'text-right' }]} />}</Async></Card>
        <Card title="By meal"><Async f={meal}>{(rows) => <Table rows={rows} cols={[{ h: 'Meal', r: (r) => cap(r.meal_type) }, { h: 'Prepared', r: (r) => num(r.prepared), cls: 'text-right' }, { h: 'Leftover', r: (r) => num(r.leftover), cls: 'text-right' }, { h: 'Waste %', r: (r) => `${num(r.waste_pct)}%`, cls: 'text-right' }]} />}</Async></Card>
        {isMgr && <div className="lg:col-span-2"><CookingAdvice compact /></div>}
      </div>
    </div>
  )
}

export function CookingAdvice({ compact = false }: { compact?: boolean }) {
  const [selectedDate, setSelectedDate] = useState(iso(addDays(new Date(), 1)))
  const advice = useFetch<any>(`/waste/cooking-advice?on=${selectedDate}`)
  const [file, setFile] = useState<File | null>(null)
  const [report, setReport] = useState<any>(null)
  const { run, busy } = useAction()
  const title = compact ? 'What to cook next' : 'Cooking recommendations'
  useEffect(() => {
    const timer = setInterval(advice.reload, 60_000)
    return () => clearInterval(timer)
  }, [advice.reload])
  const analyze = async () => {
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    const result = await run(() => api('/waste/analyze-report', { form }), 'Report analyzed')
    if (result) setReport(result)
  }
  const downloadTemplate = () => {
    const csv = 'date,meal_type,dish,attendance,prepared_kg,leftover_kg,consumed_kg,bookings\n2026-11-05,lunch,Rice,120,24,3,21,115\n'
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'waste-attendance-report-template.csv'
    link.click()
    URL.revokeObjectURL(url)
  }
  return (
    <div>
      {!compact && <PageHeader title={title} sub="Simple cooking guidance based on the next meal menu, expected attendance and recent leftovers." />}
      <Card title={compact ? title : <span className="flex items-center gap-2"><BrainCircuit className="h-4 w-4 text-brand-600" />Waste & attendance analyst <Badge tone="blue">Prototype</Badge></span>} action={<div className="flex items-end gap-2"><Field label="Meal date"><Input type="date" value={selectedDate} onChange={(e: any) => setSelectedDate(e.target.value)} /></Field><Btn size="sm" variant="secondary" onClick={advice.reload}><RefreshCw className="h-3 w-3" />Refresh</Btn></div>}>
        <p className="mb-3 text-sm text-slate-500">Live advice uses this mess's recent recorded leftovers and attendance. Upload a report below to analyze imported history. Recommendations are a prototype, not a trained machine-learning model.</p>
        <Async f={advice}>{(data) => data.recommendations.length ? <ul className="space-y-3">{data.recommendations.map((r: any, i: number) =>
          <li key={`${r.schedule_id}-${r.dish}-${i}`} className="rounded-lg border border-slate-200 p-3">
            <div className="mb-1 flex flex-wrap items-center gap-2"><Badge tone="blue">{cap(r.meal_type)}</Badge><b>{r.dish}</b><Badge tone="green">Cook about {r.suggested_kg} kg</Badge></div>
            <p className="text-sm text-slate-700">{r.action}</p>
            {r.recent_services > 0 && <p className="mt-1 text-xs text-slate-500">Recent waste: {r.recent_waste_pct}% across {r.recent_services} similar meal{r.recent_services === 1 ? '' : 's'}.</p>}
          </li>
        )}</ul> : <Empty>No meals are scheduled for this date. Add the meals and menu in Menu management first.</Empty>}</Async>
      </Card>
      <Card className="mt-5" title={<span className="flex items-center gap-2"><Upload className="h-4 w-4 text-brand-600" />Analyze an imported report</span>}>
        <p className="mb-3 text-sm text-slate-500">Upload a UTF-8 CSV with date, meal_type, dish, attendance, prepared_kg and leftover_kg columns. Optional columns: consumed_kg and bookings. Imported rows are analyzed for this view only and do not overwrite live kitchen records.</p>
        <div className="mb-4 flex flex-wrap items-end gap-3"><Field label="CSV report"><Input type="file" accept=".csv,text/csv" onChange={(e: any) => { setFile(e.target.files?.[0] || null); setReport(null) }} /></Field><Btn loading={busy} disabled={!file} onClick={analyze}>Analyze report</Btn><Btn variant="secondary" onClick={downloadTemplate}>Download CSV template</Btn></div>
        {report && <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2"><Badge tone="green">{report.rows_analyzed} rows analyzed</Badge><span className="text-xs text-slate-400">Updated {fmtDate(report.generated_at.slice(0, 10))} · {report.generated_at.slice(11, 16)}</span></div><Badge tone="amber">Prototype analysis</Badge></div>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4"><Stat label="Prepared" value={`${num(report.summary.prepared_kg)} kg`} /><Stat label="Leftover" value={`${num(report.summary.leftover_kg)} kg`} /><Stat label="Waste rate" value={`${report.summary.waste_pct}%`} tone={report.summary.waste_pct >= 15 ? 'warn' : 'good'} /><Stat label="Attendance" value={num(report.summary.attendance, 0)} /></div>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border p-3"><h3 className="mb-2 text-sm font-medium">Waste movement</h3><ResponsiveContainer width="100%" height={220}><LineChart data={report.series} {...chartProps}><CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="date" tick={{ fontSize: 10 }} /><YAxis yAxisId="left" unit="%" tick={{ fontSize: 10 }} /><YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} /><Tooltip /><Legend /><Line yAxisId="left" dataKey="waste_pct" stroke="#e11d48" name="Waste %" /><Line yAxisId="right" dataKey="attendance" stroke="#059669" name="Attendance" /></LineChart></ResponsiveContainer></div>
            <div className="rounded-xl border p-3"><h3 className="mb-2 text-sm font-medium">Leftovers by dish</h3><ResponsiveContainer width="100%" height={220}><BarChart data={report.top_dishes.slice(0, 6)} {...chartProps}><CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="dish" tick={{ fontSize: 9 }} interval={0} angle={-15} textAnchor="end" height={55} /><YAxis tick={{ fontSize: 10 }} /><Tooltip /><Bar dataKey="leftover_kg" fill="#f59e0b" name="Leftover kg" /></BarChart></ResponsiveContainer></div>
          </div>
          <div className="rounded-lg bg-brand-50 p-3"><h3 className="mb-2 text-sm font-semibold text-brand-900">What the report suggests</h3><ul className="list-disc space-y-1 pl-5 text-sm text-brand-900">{report.recommendations.map((item: string, index: number) => <li key={index}>{item}</li>)}</ul></div>
          <p className="text-xs text-slate-400">{report.model_note}</p>
        </div>}
      </Card>
    </div>
  )
}

export function MenuManagement() {
  const [tab, setTab] = useState('schedule')
  const items = useFetch<any[]>('/menu/items')
  const [start, setStart] = useState(iso(new Date()))
  const sch = useFetch<any[]>(`/menu/schedules?start=${start}&end=${iso(addDays(new Date(start), 6))}`)
  const { run, busy } = useAction()
  const [d, setD] = useState<any>({ category: 'other', diet: 'veg', ingredients: '' })
  const [s, setS] = useState<any>({ date: iso(addDays(new Date(), 1)), meal_type: 'lunch', dish_ids: [], is_holiday: false, event: '' })
  const toggle = (id: number) => setS({ ...s, dish_ids: s.dish_ids.includes(id) ? s.dish_ids.filter((x: number) => x !== id) : [...s.dish_ids, id] })
  return (
    <div>
      <PageHeader title="Menu management" sub="Maintain dishes (with portion size and cost) and publish the meal schedule students book from." />
      <Tabs tabs={[['schedule', 'Meal schedule'], ['dishes', 'Dishes']]} value={tab} onChange={setTab} />
      {tab === 'dishes' ? <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Add dish"><div className="space-y-3">
          <Field label="Name"><Input value={d.name || ''} onChange={(e: any) => setD({ ...d, name: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-3"><Field label="Category"><Select value={d.category} onChange={(e: any) => setD({ ...d, category: e.target.value })}>{['grain', 'dal', 'curry', 'bread', 'vegetable', 'snack', 'beverage', 'dairy', 'breakfast', 'dessert', 'other'].map((c) => <option key={c}>{c}</option>)}</Select></Field>
            <Field label="Diet"><Select value={d.diet} onChange={(e: any) => setD({ ...d, diet: e.target.value })}><option value="veg">Lacto-vegetarian</option><option value="vegan">Vegan</option></Select></Field>
            <Field label="Portion (kg cooked)"><Input type="number" step="0.01" value={d.portion_kg || ''} onChange={(e: any) => setD({ ...d, portion_kg: +e.target.value })} /></Field><Field label="Cost per kg"><Input type="number" value={d.cost_per_kg ?? ''} onChange={(e: any) => setD({ ...d, cost_per_kg: +e.target.value })} /></Field></div>
          <Field label="Ingredients (comma-separated)" hint="Declare every ingredient; animal products, meat, fish, seafood and eggs are not allowed"><Input required value={d.ingredients} onChange={(e: any) => setD({ ...d, ingredients: e.target.value })} placeholder="e.g. lentils, tomato, spices" /></Field>
          <Btn loading={busy} onClick={() => run(async () => { await api('/menu/items', { body: { ...d, ingredients: d.ingredients.split(',').map((i: string) => i.trim()).filter(Boolean) } }); setD({ category: 'other', diet: 'veg', ingredients: '' }); items.reload() }, 'Dish added')}>Add dish</Btn></div></Card>
        <Card title="Dishes" className="lg:col-span-2"><Async f={items}>{(rows) => <Table rows={rows} cols={[{ h: 'Dish', r: (r) => r.name }, { h: 'Category', r: (r) => cap(r.category) }, { h: 'Diet', r: (r) => cap(r.diet) }, { h: 'Portion kg', r: (r) => r.portion_kg, cls: 'text-right' }, { h: 'Cost/kg', r: (r) => r.cost_per_kg, cls: 'text-right' }]} />}</Async></Card></div>
        : <div className="grid gap-6 lg:grid-cols-3">
          <Card title="Add meal to schedule"><div className="space-y-3">
            <div className="grid grid-cols-2 gap-3"><Field label="Date"><Input type="date" value={s.date} onChange={(e: any) => setS({ ...s, date: e.target.value })} /></Field><Field label="Meal"><Select value={s.meal_type} onChange={(e: any) => setS({ ...s, meal_type: e.target.value })}>{MEALS.map((m) => <option key={m} value={m}>{cap(m)}</option>)}</Select></Field></div>
            <Field label="Dishes"><div className="max-h-48 space-y-1 overflow-y-auto rounded-lg border p-2">{items.data?.map((i: any) => <label key={i.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={s.dish_ids.includes(i.id)} onChange={() => toggle(i.id)} />{i.name}</label>)}</div></Field>
            <Field label="Special event (optional)"><Input value={s.event} onChange={(e: any) => setS({ ...s, event: e.target.value })} /></Field>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={s.is_holiday} onChange={(e) => setS({ ...s, is_holiday: e.target.checked })} />Institutional holiday (no booking)</label>
            <Btn loading={busy} onClick={() => run(async () => { await api('/menu/schedules', { body: { ...s, event: s.event || null } }); sch.reload() }, 'Meal scheduled')}>Add to schedule</Btn></div></Card>
          <Card title="Schedule" className="lg:col-span-2" action={<Input type="date" className="w-40" value={start} onChange={(e: any) => setStart(e.target.value)} />}><Async f={sch}>{(rows) => <Table rows={rows} empty="Nothing scheduled in this week." cols={[{ h: 'Date', r: (r) => fmtDate(r.date) }, { h: 'Meal', r: (r) => cap(r.meal_type) }, { h: 'Dishes', r: (r) => r.dishes.map((x: any) => x.name).join(', ') || '-' }, { h: 'Booked', r: (r) => r.active_bookings, cls: 'text-right' }, { h: '', r: (r) => r.is_holiday ? <Badge tone="amber">Holiday</Badge> : r.event ? <Badge tone="blue">{r.event}</Badge> : null }, { h: '', r: (r) => r.active_bookings === 0 && r.headcount === null && <Btn size="sm" variant="secondary" onClick={() => run(async () => { await api(`/menu/schedules/${r.id}`, { method: 'DELETE' }); sch.reload() }, 'Removed')}>Delete</Btn> }]} />}</Async></Card></div>}
    </div>
  )
}

export function MenuOptimisation() {
  const ins = useFetch<any>('/menu-opt/insights'); const { run, busy } = useAction()
  return (
    <div>
      <PageHeader title="Menu optimisation" sub="Suggestions backed by recorded waste, consumption, ratings and preferences. They are advisory - you decide." action={<Btn variant="secondary" loading={busy} onClick={() => run(async () => { await api('/menu-opt/generate', { method: 'POST' }) }, 'Recommendations saved')}>Save current recommendations</Btn>} />
      <Async f={ins}>{(d) => <div className="space-y-6">
        <Card title="Recommendations">{d.recommendations.length ? <ul className="space-y-3">{d.recommendations.map((r: any, i: number) => <li key={i} className="rounded-lg border border-slate-200 p-3 text-sm"><Badge tone={r.kind === 'popular' ? 'green' : r.kind === 'combination' ? 'blue' : 'amber'}>{cap(r.kind)}</Badge><p className="mt-1">{r.message}</p></li>)}</ul> : <Empty>No evidence-backed recommendations yet. More recorded services per dish are needed.</Empty>}<p className="mt-3 text-xs text-slate-400">{d.note}</p></Card>
        <Card title={`Dish performance (last ${d.window_days} days)`}><Table rows={d.dish_stats} cols={[{ h: 'Dish', r: (r) => r.item }, { h: 'Services', r: (r) => r.services, cls: 'text-right' }, { h: 'Avg waste', r: (r) => <Badge tone={r.avg_waste_pct > 20 ? 'red' : r.avg_waste_pct > 10 ? 'amber' : 'green'}>{r.avg_waste_pct}%</Badge>, cls: 'text-right' }, { h: 'High-waste services', r: (r) => `${r.high_waste_share_pct}%`, cls: 'text-right' }, { h: 'Portion uptake', r: (r) => r.avg_uptake === null ? '-' : `${Math.round(r.avg_uptake * 100)}%`, cls: 'text-right' }, { h: 'Rating', r: (r) => r.avg_rating ? `${r.avg_rating} (${r.ratings})` : '-', cls: 'text-right' }, { h: 'Likes / dislikes', r: (r) => `${r.likes} / ${r.dislikes}`, cls: 'text-right' }, { h: 'Loss', r: (r) => num(r.loss, 0), cls: 'text-right' }]} /></Card>
        <div className="grid gap-6 md:grid-cols-2"><Card title="Menu combinations with lowest waste"><Table rows={(d.best_combinations || []).map((c: any, i: number) => ({ id: i, ...c }))} cols={[{ h: 'Pair', r: (r) => r.pair }, { h: 'Times', r: (r) => r.times }, { h: 'Waste', r: (r) => `${r.avg_waste_pct}% (${r.vs_overall_pp > 0 ? '+' : ''}${r.vs_overall_pp} pp)` }]} /></Card>
          <Card title="Menu combinations with highest waste"><Table rows={(d.worst_combinations || []).map((c: any, i: number) => ({ id: i, ...c }))} cols={[{ h: 'Pair', r: (r) => r.pair }, { h: 'Times', r: (r) => r.times }, { h: 'Waste', r: (r) => `${r.avg_waste_pct}% (${r.vs_overall_pp > 0 ? '+' : ''}${r.vs_overall_pp} pp)` }]} /></Card></div></div>}</Async>
    </div>
  )
}
