import { X } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(' ')
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight text-white sm:text-3xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-zinc-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

const BADGE_TONES = {
  violet: 'bg-nova-500/15 text-nova-300 ring-nova-500/30',
  cyan: 'bg-pulse-500/15 text-pulse-300 ring-pulse-500/30',
  green: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  amber: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  red: 'bg-red-500/15 text-red-300 ring-red-500/30',
  zinc: 'bg-zinc-500/15 text-zinc-300 ring-zinc-500/30',
} as const
export type Tone = keyof typeof BADGE_TONES

export function Badge({ tone = 'zinc', children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1', BADGE_TONES[tone], className)}>
      {children}
    </span>
  )
}

const STATUS_TONES: Record<string, Tone> = {
  ready: 'green', analyzed: 'green', completed: 'green', approved: 'green', authorized: 'green',
  pending: 'zinc', queued: 'zinc', unknown: 'zinc',
  copying: 'cyan', probing: 'cyan', analyzing: 'cyan', running: 'cyan', detected: 'violet',
  error: 'red', failed: 'red', denied: 'red', rejected: 'red',
  cancelled: 'amber', review: 'amber',
}
const STATUS_LABELS: Record<string, string> = {
  ready: 'pronto', analyzed: 'analizzato', completed: 'completato', pending: 'in attesa', queued: 'in coda',
  copying: 'copia', probing: 'lettura', analyzing: 'analisi', running: 'in corso', error: 'errore',
  failed: 'fallito', cancelled: 'annullato', detected: 'rilevata', review: 'revisione', rejected: 'scartata', archived: 'archiviata', authorized: 'autorizzato', denied: 'negato', unknown: 'sconosciuto',
}

export function StatusBadge({ status }: { status: string }) {
  const tone = STATUS_TONES[status] ?? 'zinc'
  const live = tone === 'cyan'
  return (
    <Badge tone={tone}>
      {live && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-pulse-400" />}
      {STATUS_LABELS[status] ?? status}
    </Badge>
  )
}

export function ProgressBar({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cx('h-1.5 w-full overflow-hidden rounded-full bg-ink-700', className)}>
      <div
        className="h-full rounded-full bg-gradient-to-r from-nova-500 to-pulse-400 transition-[width] duration-500"
        style={{ width: `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%` }}
      />
    </div>
  )
}

export function Modal({ open, onClose, title, children, wide }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm sm:p-8"
         onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div role="dialog" aria-modal="true" aria-label={title}
           className={cx('card w-full shadow-2xl shadow-nova-900/30', wide ? 'max-w-4xl' : 'max-w-xl')}>
        <div className="flex items-center justify-between border-b border-ink-700 px-5 py-4">
          <h2 className="font-display text-lg font-semibold text-white">{title}</h2>
          <button className="rounded-md p-1 text-zinc-400 hover:bg-ink-700 hover:text-white" onClick={onClose} aria-label="Chiudi">
            <X size={18} />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}

export function EmptyState({ icon, title, text, action }: { icon: ReactNode; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-4 rounded-2xl bg-nova-500/10 p-4 text-nova-400 ring-1 ring-nova-500/30">{icon}</div>
      <h3 className="font-display text-lg font-semibold text-white">{title}</h3>
      {text && <p className="mt-1 max-w-md text-sm text-zinc-400">{text}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function Spinner({ className }: { className?: string }) {
  return <span className={cx('inline-block h-4 w-4 animate-spin rounded-full border-2 border-nova-400 border-t-transparent', className)} />
}

export function ErrorBox({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="card flex items-center justify-between gap-4 border-red-500/40 bg-red-500/5 px-4 py-3 text-sm text-red-200">
      <span>{error.message}</span>
      {onRetry && <button className="btn-ghost" onClick={onRetry}>Riprova</button>}
    </div>
  )
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-zinc-500">{hint}</span>}
    </label>
  )
}
