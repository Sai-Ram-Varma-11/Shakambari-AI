import { useState } from 'react'
import { Link } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import { ThumbsDown, ThumbsUp, Star } from 'lucide-react'
import { addDays, api, cap, fmtDate, fmtTime, iso, num, useAction, useAuth, useFetch, MEALS } from '../lib'
import { Async, Badge, Btn, Card, Empty, Field, Input, Modal, PageHeader, Select, Stat, Status, Table } from '../ui'

function MealCard({ s, prefs, onPref, reload }: any) {
  const { run, busy } = useAction()
  const toggle = () => run(async () => { s.my_booking === 'booked' ? await api(`/bookings/${s.id}`, { method: 'DELETE', body: {} }) : await api('/bookings', { body: { schedule_id: s.id } }); reload() }, s.my_booking === 'booked' ? 'Booking cancelled' : 'Meal booked')
  const closed = !s.bookable
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between">
        <div><div className="font-medium">{cap(s.meal_type)}</div><div className="text-xs text-slate-500">{s.is_holiday ? 'No service (holiday)' : `Booking closes ${fmtTime(s.cutoff_at)}`}</div></div>
        {s.my_booking === 'booked' ? <Badge tone="green">Booked</Badge> : s.my_booking === 'cancelled' ? <Badge tone="red">Cancelled</Badge> : closed ? <Badge>Closed</Badge> : <Badge tone="amber">Not booked</Badge>}
      </div>
      {s.event && <div className="mt-1 text-xs font-medium text-brand-700">{s.event}</div>}
      <ul className="mt-3 flex flex-wrap gap-1.5">{s.dishes.map((d: any) => (
        <li key={d.id} className="flex items-center gap-1 rounded-full bg-slate-100 py-0.5 pl-2.5 pr-1 text-xs">
          <span>{d.name}</span><span className="text-[10px] text-slate-400">{d.diet === 'vegan' ? 'VG' : 'V'}</span>
          {onPref && <><button aria-label={`Like ${d.name}`} onClick={() => onPref(d.id, prefs[d.id] === 'like' ? null : 'like')} className={`rounded-full p-1 ${prefs[d.id] === 'like' ? 'bg-emerald-200 text-emerald-800' : 'text-slate-400 hover:text-emerald-700'}`}><ThumbsUp className="h-3 w-3" /></button>
            <button aria-label={`Dislike ${d.name}`} onClick={() => onPref(d.id, prefs[d.id] === 'dislike' ? null : 'dislike')} className={`rounded-full p-1 ${prefs[d.id] === 'dislike' ? 'bg-rose-200 text-rose-800' : 'text-slate-400 hover:text-rose-700'}`}><ThumbsDown className="h-3 w-3" /></button></>}
        </li>))}{!s.dishes.length && <li className="text-xs text-slate-400">Menu not published yet</li>}</ul>
      <div className="mt-3 flex items-center justify-between text-xs text-slate-500"><span>{s.active_bookings} students booked</span>
        <Btn size="sm" variant={s.my_booking === 'booked' ? 'secondary' : 'primary'} loading={busy} disabled={closed && s.my_booking !== 'booked' || (closed && s.my_booking === 'booked')} onClick={toggle}>{s.my_booking === 'booked' ? 'Cancel booking' : 'Book meal'}</Btn></div>
    </div>
  )
}

export function StudentDashboard() {
  const { user } = useAuth()
  const stats = useFetch<any>('/bookings/stats/mine')
  const sched = useFetch<any[]>(`/menu/schedules?start=${iso(new Date())}&end=${iso(addDays(new Date(), 1))}`)
  return (
    <div>
      <PageHeader title={`Hello, ${user.name.split(' ')[0]}`} sub="Book before the cutoff so the kitchen can cook the right amount." action={<Link className="btn-primary" to="/book">Open meal calendar</Link>} />
      <Async f={stats}>{(s) => <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4"><Stat label="Meals booked" value={s.booked} /><Stat label="Attended" value={s.attended} /><Stat label="Cancelled" value={s.cancelled} /><Stat label="Show-up rate" value={s.attendance_rate === null ? '-' : `${s.attendance_rate}%`} sub={`${s.no_shows} booked but not attended`} tone={s.no_shows > 5 ? 'warn' : 'good'} /></div>}</Async>
      <Async f={sched}>{(rows) => {
        const days = Array.from(new Set(rows.map((r: any) => r.date)))
        return days.length ? <>{days.map((d: any) => <div key={d} className="mb-6"><h2 className="mb-2 text-sm font-semibold text-slate-700">{fmtDate(d)}</h2><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">{MEALS.map((m) => rows.find((r: any) => r.date === d && r.meal_type === m)).filter(Boolean).map((s: any) => <MealCard key={s.id} s={s} reload={sched.reload} />)}</div></div>)}</> : <Empty>No meals scheduled for today or tomorrow yet.</Empty>
      }}</Async>
    </div>
  )
}

export function BookMeals() {
  const [selectedDate, setSelectedDate] = useState(iso(new Date()))
  const sched = useFetch<any[]>(`/menu/schedules?start=${selectedDate}&end=${selectedDate}`)
  const prefs = useFetch<any>('/bookings/preferences')
  const { run } = useAction()
  const setPref = (id: number, p: string | null) => run(async () => { await api('/bookings/preferences', { method: 'PUT', body: { menu_item_id: id, preference: p } }); prefs.reload() })
  const sessions = [
    { title: 'Morning', meals: ['breakfast'] },
    { title: 'Afternoon', meals: ['lunch'] },
    { title: 'Evening', meals: ['snacks', 'dinner'] },
  ]
  return (
    <div>
      <PageHeader title="Book meals" sub="Choose a date to see its meal menu. Each meal has its own booking cutoff; book or cancel before the time shown." action={<div className="flex items-center gap-2"><Btn variant="secondary" size="sm" onClick={() => setSelectedDate(iso(addDays(new Date(selectedDate), -1)))}>Previous day</Btn><Input aria-label="Choose meal date" type="date" value={selectedDate} onChange={(e: any) => setSelectedDate(e.target.value)} className="w-40" /><Btn variant="secondary" size="sm" onClick={() => setSelectedDate(iso(addDays(new Date(selectedDate), 1)))}>Next day</Btn></div>} />
      <Async f={sched}>{(rows) => {
        const byMeal = new Map(rows.map((row: any) => [row.meal_type, row]))
        return <div>
          <h2 className="mb-4 text-sm font-semibold text-slate-700">{fmtDate(selectedDate)}</h2>
          {sessions.map((session) => {
            const meals = session.meals.map((meal) => byMeal.get(meal)).filter(Boolean)
            return <section key={session.title} className="mb-6">
              <h3 className="mb-2 text-sm font-semibold text-slate-600">{session.title}</h3>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {meals.length ? meals.map((s: any) => <MealCard key={s.id} s={s} prefs={prefs.data || {}} onPref={setPref} reload={sched.reload} />) : <p className="text-sm text-slate-400">No meal menu published for this session.</p>}
              </div>
            </section>
          })}
        </div>
      }}</Async>
    </div>
  )
}

export function MealHistory() {
  const h = useFetch<any[]>('/bookings/mine?limit=100')
  const [rate, setRate] = useState<any>(null); const [stars, setStars] = useState(4); const [comment, setComment] = useState('')
  const [mealPass, setMealPass] = useState<any>(null)
  const { run, busy } = useAction()
  const submit = async () => { const r = await run(() => api('/bookings/rate', { body: { menu_item_id: rate.dish.id, schedule_id: rate.sid, rating: stars, comment: comment || null } }), 'Thanks for your feedback'); if (r) { setRate(null); setComment(''); h.reload() } }
  const showPass = async (scheduleId: number) => {
    const result = await run(() => api(`/bookings/${scheduleId}/pass`))
    if (result) setMealPass(result)
  }
  return (
    <div>
      <PageHeader title="Meal history" sub="Your bookings and attendance. Rate dishes from meals you attended." />
      <Card><Async f={h}>{(rows) => <Table rows={rows} empty="No bookings yet." cols={[
        { h: 'Date', r: (r) => fmtDate(r.date) }, { h: 'Meal', r: (r) => cap(r.meal_type) }, { h: 'Booking', r: (r) => <Status s={r.status} /> },
        { h: 'Attended', r: (r) => (r.attended ? <Badge tone="green">Yes</Badge> : <span className="text-slate-400">No</span>) },
        { h: 'Meal pass', r: (r) => r.status === 'booked' ? <Btn size="sm" variant="secondary" onClick={() => showPass(r.schedule_id)}>Show QR</Btn> : <span className="text-slate-300">-</span> },
        { h: 'Rate dishes', r: (r) => r.attended ? <div className="flex flex-wrap gap-1">{r.dishes.map((d: any) => d.rated ? <Badge key={d.id}>{d.name} ✓</Badge> : <Btn key={d.id} size="sm" variant="secondary" onClick={() => setRate({ sid: r.schedule_id, dish: d })}><Star className="h-3 w-3" />{d.name}</Btn>)}</div> : <span className="text-slate-300">-</span> },
      ]} />}</Async></Card>
      <Modal open={!!mealPass} onClose={() => setMealPass(null)} title="Your meal pass">
        {mealPass && <div className="flex flex-col items-center gap-3 text-center"><p className="text-sm text-slate-600">{fmtDate(mealPass.date)} · {cap(mealPass.meal_type)}</p><QRCodeSVG value={mealPass.pass_token} size={220} includeMargin /><p className="text-xs text-slate-500">Show this QR code to mess staff when you arrive. It expires {fmtTime(mealPass.expires_at)}.</p></div>}
      </Modal>
      <Modal open={!!rate} onClose={() => setRate(null)} title={`Rate ${rate?.dish.name}`}>
        <div className="space-y-3"><Field label="Rating"><Select value={stars} onChange={(e: any) => setStars(+e.target.value)}>{[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{n} - {['', 'Poor', 'Fair', 'Good', 'Very good', 'Excellent'][n]}</option>)}</Select></Field>
          <Field label="Comment (optional)"><Input maxLength={500} value={comment} onChange={(e: any) => setComment(e.target.value)} /></Field><Btn loading={busy} onClick={submit}>Submit</Btn></div>
      </Modal>
    </div>
  )
}
