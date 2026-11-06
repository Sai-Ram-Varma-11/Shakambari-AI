import { CalendarCheck, ChefHat, Gauge, HeartHandshake, Package, Trash2 } from 'lucide-react'

export function PlateArt({ className = 'h-24 w-24' }: { className?: string }) {
  return (
    <svg viewBox="0 0 120 120" className={className} aria-hidden="true">
      <circle cx="60" cy="64" r="44" fill="#ECF3E8" /><circle cx="60" cy="64" r="34" fill="none" stroke="#14532D" strokeWidth="3" opacity=".7" />
      <circle cx="60" cy="64" r="24" fill="#FDE9B8" />
      <path d="M60 70V52" stroke="#14532D" strokeWidth="3" strokeLinecap="round" />
      <path d="M60 56c-9 1-15-5-16-14 9-1 15 5 16 14z" fill="#14532D" /><path d="M60 56c9 1 15-5 16-14-9-1-15 5-16 14z" fill="#16803D" />
      <path d="M44 28c-3-3 3-5 0-9M76 28c3-3-3-5 0-9" fill="none" stroke="#F59E0B" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

/** Illustrated thali, drawn in SVG (no photo needed). Replace via PHOTOS.hero if you have a real photo. */
export function ThaliHero({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 480 440" className={className} role="img" aria-label="Illustration of a steel thali with dal, vegetables, rice and chapati, with sprouting leaves">
      <defs>
        <radialGradient id="steel" cx="40%" cy="35%"><stop offset="0" stopColor="#F4F6F4" /><stop offset="1" stopColor="#B9C4BC" /></radialGradient>
        <radialGradient id="glow" cx="50%" cy="50%"><stop offset="0" stopColor="#FDE9B8" /><stop offset="1" stopColor="#FDE9B8" stopOpacity="0" /></radialGradient>
      </defs>
      <circle cx="250" cy="230" r="215" fill="url(#glow)" />
      <path d="M150 70c-8-14 10-22 0-40M250 56c-8-14 10-22 0-40M350 70c-8-14 10-22 0-40" fill="none" stroke="#F59E0B" strokeWidth="6" strokeLinecap="round" opacity=".85" />
      <ellipse cx="250" cy="350" rx="170" ry="22" fill="#14532D" opacity=".12" />
      <circle cx="250" cy="230" r="170" fill="url(#steel)" /><circle cx="250" cy="230" r="150" fill="none" stroke="#9FAEA4" strokeWidth="3" />
      <circle cx="250" cy="230" r="128" fill="#E6ECE7" />
      {/* katoris */}
      <circle cx="190" cy="170" r="42" fill="#C9D3CC" /><circle cx="190" cy="170" r="34" fill="#E8A317" /><circle cx="180" cy="162" r="9" fill="#F7C75A" opacity=".8" />
      <circle cx="310" cy="170" r="42" fill="#C9D3CC" /><circle cx="310" cy="170" r="34" fill="#C2410C" /><circle cx="300" cy="164" r="7" fill="#16803D" /><circle cx="322" cy="176" r="6" fill="#16803D" /><circle cx="302" cy="184" r="6" fill="#F59E0B" />
      <circle cx="250" cy="288" r="46" fill="#C9D3CC" /><circle cx="250" cy="288" r="38" fill="#FFFDF6" />
      {Array.from({ length: 16 }).map((_, i) => <ellipse key={i} cx={236 + (i % 4) * 9} cy={274 + Math.floor(i / 4) * 9} rx="5" ry="2.4" fill="#EDE6D2" transform={`rotate(${i * 20} ${236 + (i % 4) * 9} ${274 + Math.floor(i / 4) * 9})`} />)}
      <circle cx="160" cy="276" r="40" fill="#E9C37E" /><circle cx="160" cy="276" r="40" fill="none" stroke="#C99A4B" strokeWidth="3" /><circle cx="150" cy="268" r="3" fill="#B7843A" /><circle cx="170" cy="284" r="3" fill="#B7843A" /><circle cx="168" cy="262" r="2.5" fill="#B7843A" />
      <circle cx="340" cy="276" r="40" fill="#E9C37E" /><circle cx="340" cy="276" r="40" fill="none" stroke="#C99A4B" strokeWidth="3" /><circle cx="330" cy="270" r="3" fill="#B7843A" /><circle cx="350" cy="286" r="3" fill="#B7843A" />
      {/* sprouting leaves */}
      <path d="M250 232V196" stroke="#14532D" strokeWidth="5" strokeLinecap="round" />
      <path d="M250 202c-26 2-46-14-50-42 26-3 46 13 50 42z" fill="#14532D" /><path d="M250 202c26 2 46-14 50-42-26-3-46 13-50 42z" fill="#16803D" />
      <path d="M72 300c18-26 46-30 62-18-8 24-36 34-62 18zM428 300c-18-26-46-30-62-18 8 24 36 34 62 18z" fill="#16803D" opacity=".9" />
    </svg>
  )
}

const NODES = [
  [CalendarCheck, 'Booking'], [Gauge, 'Forecast'], [ChefHat, 'Cook'], [Trash2, 'Waste'], [Package, 'Surplus'], [HeartHandshake, 'NGO'],
] as const

/** Animated closed-loop diagram: booking → forecast → cook → waste → surplus → NGO → (feeds back to booking). */
export function LoopDiagram() {
  const R = 40 // % radius
  return (
    <div className="relative mx-auto aspect-square w-full max-w-[420px]" role="img" aria-label="Closed loop: booking, forecast, cook, waste, surplus, NGO, then back to booking">
      <svg viewBox="0 0 100 100" className="absolute inset-0 h-full w-full">
        <circle cx="50" cy="50" r={R} fill="none" stroke="rgb(var(--bd))" strokeWidth="1.2" />
        <circle cx="50" cy="50" r={R} fill="none" stroke="#F59E0B" strokeWidth="1.2" strokeLinecap="round" strokeDasharray="2 22" className="animate-flow" style={{ transformOrigin: 'center' }} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center"><span className="font-display text-lg font-bold text-brand">Closed loop</span><span className="max-w-[9rem] text-xs text-sub">Every meal teaches the next forecast</span></div>
      {NODES.map(([Icon, label], i) => {
        const a = (i / NODES.length) * 2 * Math.PI - Math.PI / 2
        return (
          <div key={label} className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-1" style={{ left: `${50 + R * Math.cos(a)}%`, top: `${50 + R * Math.sin(a)}%` }}>
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl border border-bd bg-surface text-brand shadow-soft sm:h-14 sm:w-14"><Icon className="h-5 w-5 sm:h-6 sm:w-6" /></span>
            <span className="rounded-full bg-bg/90 px-1.5 text-[11px] font-semibold text-fg sm:text-xs">{i + 1}. {label}</span>
          </div>
        )
      })}
    </div>
  )
}
