import { ReactNode, useEffect, useState } from 'react'
import { api, cap } from './lib'
import { AlertCircle, Loader2, X } from 'lucide-react'

export const Card = ({ title, action, children, className = '' }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) => (
  <section className={`card ${className}`}>
    {(title || action) && <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3"><h2 className="text-sm font-semibold text-slate-900">{title}</h2>{action}</header>}
    <div className="p-4">{children}</div>
  </section>
)
export const PageHeader = ({ title, sub, action }: { title: string; sub?: ReactNode; action?: ReactNode }) => (
  <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
    <div><h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>{sub && <p className="mt-1 text-sm text-slate-500">{sub}</p>}</div>{action}
  </div>
)
export const Stat = ({ label, value, sub, tone = 'default' }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'default' | 'good' | 'warn' | 'bad' }) => (
  <div className="card p-4">
    <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
    <div className={`mt-1 text-2xl font-semibold ${tone === 'good' ? 'text-brand-700' : tone === 'warn' ? 'text-amber-600' : tone === 'bad' ? 'text-rose-600' : 'text-slate-900'}`}>{value}</div>
    {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
  </div>
)
const tones: any = { green: 'bg-emerald-50 text-emerald-700 ring-emerald-200', amber: 'bg-amber-50 text-amber-700 ring-amber-200', red: 'bg-rose-50 text-rose-700 ring-rose-200', blue: 'bg-sky-50 text-sky-700 ring-sky-200', slate: 'bg-slate-100 text-slate-600 ring-slate-200' }
export const Badge = ({ tone = 'slate', children }: { tone?: string; children: ReactNode }) => <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${tones[tone]}`}>{children}</span>
export const statusTone = (s: string) => ({ eligible: 'green', approved: 'green', delivered: 'green', collected: 'green', closed: 'green', booked: 'green', high: 'green', within_range: 'green', pending: 'amber', pending_review: 'amber', preparing: 'amber', medium: 'amber', warning: 'amber', served: 'blue', picked_up: 'blue', info: 'blue', ineligible: 'red', rejected: 'red', expired: 'red', cancelled: 'red', critical: 'red', low: 'red', shortage_risk: 'red', surplus_risk: 'amber' } as any)[s] || 'slate'
export const Status = ({ s }: { s: string }) => <Badge tone={statusTone(s)}>{cap(s)}</Badge>
export const DataType = ({ t }: { t: string }) => <Badge tone={t === 'measured' ? 'green' : t === 'calculated' ? 'blue' : 'amber'}>{cap(t)}</Badge>

export const Btn = ({ variant = 'primary', size, loading, children, ...p }: any) => (
  <button {...p} disabled={p.disabled || loading} className={`btn-${variant} ${size === 'sm' ? 'btn-sm' : ''} ${p.className || ''}`}>{loading && <Loader2 className="h-4 w-4 animate-spin" />}{children}</button>
)
export const Field = ({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) => <label className="block"><span className="label">{label}</span>{children}{hint && <span className="mt-1 block text-xs text-slate-400">{hint}</span>}</label>
export const Input = (p: any) => <input {...p} className={`input ${p.className || ''}`} />
export const Select = ({ children, ...p }: any) => <select {...p} className={`input ${p.className || ''}`}>{children}</select>
export const Loading = () => <div className="flex items-center justify-center gap-2 py-12 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />Loading…</div>
export const ErrorBox = ({ msg, retry }: { msg: string; retry?: () => void }) => (
  <div role="alert" className="flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" /><div className="flex-1">{msg}</div>{retry && <button className="font-medium underline" onClick={retry}>Retry</button>}</div>
)
export const Empty = ({ children }: { children: ReactNode }) => <div className="rounded-lg border border-dashed border-slate-300 py-10 text-center text-sm text-slate-500">{children}</div>
export const Async = ({ f, children }: { f: { data: any; loading: boolean; error: string; reload: () => void }; children: (d: any) => ReactNode }) =>
  f.loading && !f.data ? <Loading /> : f.error ? <ErrorBox msg={f.error} retry={f.reload} /> : f.data ? <>{children(f.data)}</> : null

export function Table({ cols, rows, empty = 'No data yet.' }: { cols: { h: string; r: (row: any) => ReactNode; cls?: string }[]; rows: any[]; empty?: string }) {
  if (!rows || !rows.length) return <Empty>{empty}</Empty>
  return <div className="overflow-x-auto"><table className="tbl"><thead><tr>{cols.map((c, i) => <th key={i} className={c.cls}>{c.h}</th>)}</tr></thead><tbody>{rows.map((r, i) => <tr key={r.id ?? i}>{cols.map((c, j) => <td key={j} className={c.cls}>{c.r(r)}</td>)}</tr>)}</tbody></table></div>
}
export function Modal({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  useEffect(() => { const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose(); if (open) addEventListener('keydown', h); return () => removeEventListener('keydown', h) }, [open])
  if (!open) return null
  return <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}><div role="dialog" aria-modal="true" aria-label={title} className="card max-h-[90vh] w-full max-w-lg overflow-y-auto p-5" onClick={(e) => e.stopPropagation()}><div className="mb-4 flex items-center justify-between"><h3 className="font-semibold">{title}</h3><button aria-label="Close" onClick={onClose}><X className="h-4 w-4" /></button></div>{children}</div></div>
}
export function Tabs({ tabs, value, onChange }: { tabs: [string, string][]; value: string; onChange: (v: string) => void }) {
  return <div role="tablist" className="mb-4 flex gap-1 border-b border-slate-200">{tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={value === k} onClick={() => onChange(k)} className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${value === k ? 'border-brand-600 text-brand-700' : 'border-transparent text-slate-500 hover:text-slate-800'}`}>{l}</button>)}</div>
}
export function AuthImage({ id, className }: { id: number; className?: string }) {
  const [src, setSrc] = useState('')
  useEffect(() => { let u = ''; api<Blob>(`/vision/${id}/image`, { raw: true }).then((b) => { u = URL.createObjectURL(b); setSrc(u) }).catch(() => {}); return () => { if (u) URL.revokeObjectURL(u) } }, [id])
  return src ? <img src={src} alt="Leftover food observation" className={className} /> : <div className={`${className} bg-slate-100`} />
}
export const DemoBanner = ({ user }: { user: any }) => user?.institution?.data_mode === 'demo' ? <div className="bg-amber-100 px-4 py-1.5 text-center text-xs font-medium text-amber-900">Synthetic demonstration data - not real institutional data</div> : null
