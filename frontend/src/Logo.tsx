// Original Shakambari mark: steel bowl, turmeric rim, sprouting leaf pair, steam. Mirrors public/logo.svg.
export function Logo({ size = 32, className = '', steam = true }: { size?: number; className?: string; steam?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" className={className} role="img" aria-label="Shakambari AI logo">
      <rect width="64" height="64" rx="14" fill="#FBF7EE" />
      {steam && size >= 28 && <path d="M15 22c-3-3 3-5 0-9M49 22c3-3-3-5 0-9" fill="none" stroke="#F59E0B" strokeWidth="2.4" strokeLinecap="round" />}
      <path d="M10 36h44c0 11-9 19-22 19S10 47 10 36z" fill="#14532D" />
      <ellipse cx="32" cy="36" rx="22" ry="4.2" fill="#F59E0B" />
      <path d="M32 34V25" stroke="#14532D" strokeWidth="2.6" strokeLinecap="round" />
      <path d="M32 27C25 28 19 23 17 14c8-1 14 4 15 13z" fill="#14532D" />
      <path d="M32 27c7 1 13-4 15-13-8-1-14 4-15 13z" fill="#15803D" />
    </svg>
  )
}
export const Brand = ({ size = 32, sub = false }: { size?: number; sub?: boolean }) => (
  <span className="flex items-center gap-2.5">
    <Logo size={size} className="shrink-0 rounded-xl shadow-soft" />
    <span className="leading-none"><span className="font-display text-lg font-bold text-brand">Shakambari <span className="text-turmeric-500">AI</span></span>{sub && <span className="mt-1 block text-[10px] font-medium text-sub">Think Smart. Serve Right. Waste Less.</span>}</span>
  </span>
)
