import { ReactNode } from 'react'
// Shared Recharts theme: green / turmeric / terracotta, rounded bars, light grid (grid + text colours come from index.css).
export const C = { green: '#16803D', deep: '#14532D', turmeric: '#F59E0B', terracotta: '#C2410C', ink: '#8A9A8D' }
export const chartMargin = { top: 8, right: 10, left: 0, bottom: 0 }
export const barRadius: [number, number, number, number] = [6, 6, 0, 0]
export const axis = { tick: { fontSize: 11 }, tickLine: false, axisLine: false } as const
export function ChartTip({ active, payload, label, unit = '' }: { active?: boolean; payload?: any[]; label?: ReactNode; unit?: string }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-xl border border-bd bg-surface px-3 py-2 text-xs shadow-lift">
      <div className="mb-1 font-semibold text-fg">{label}</div>
      {payload.map((p, i) => <div key={i} className="flex items-center gap-2 text-sub"><span className="h-2 w-2 rounded-full" style={{ background: p.color || p.fill }} />{p.name}: <b className="text-fg">{typeof p.value === 'number' ? Math.round(p.value * 100) / 100 : p.value}{unit}</b></div>)}
    </div>
  )
}
export function Sparkline({ data, good = 'down' }: { data: number[]; good?: 'up' | 'down' }) {
  if (!data || data.length < 2) return null
  const w = 84, h = 28, min = Math.min(...data), max = Math.max(...data), r = max - min || 1
  const pts = data.map((v, i) => [(i / (data.length - 1)) * w, h - 3 - ((v - min) / r) * (h - 6)])
  const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ')
  const improving = good === 'down' ? data[data.length - 1] <= data[0] : data[data.length - 1] >= data[0]
  return <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true"><path d={d} fill="none" stroke={improving ? C.green : C.terracotta} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
}
