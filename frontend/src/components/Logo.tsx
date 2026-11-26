/** SPECForge mark: three linked nodes over an anvil spark. */
export function Logo({ className = 'size-8' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <rect width="32" height="32" rx="8" fill="#4f46e5" />
      <path d="M9 11 L16 20 L23 11" stroke="#c7d2fe" strokeWidth="2" fill="none" strokeLinecap="round" />
      <circle cx="9" cy="11" r="3" fill="#fff" />
      <circle cx="23" cy="11" r="3" fill="#fff" />
      <circle cx="16" cy="21" r="3.5" fill="#f59e0b" />
      <path d="M16 26.5 v1.5 M12.5 25.5 l-1 1 M19.5 25.5 l1 1" stroke="#fcd34d" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  )
}
