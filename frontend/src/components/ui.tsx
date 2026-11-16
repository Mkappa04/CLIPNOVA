import { AlertTriangle } from 'lucide-react'
import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { stageOf } from './nav'
import { Dialog } from './ui/dialog'

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(' ')
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  const { pathname } = useLocation()
  const stage = stageOf(pathname)
  return (
    <header className="mb-7 flex flex-wrap items-end justify-between gap-x-6 gap-y-4 border-b border-graphite-700 pb-5">
      <div className="min-w-0">
        {stage && (
          <div className="eyebrow mb-2 flex items-center gap-2">
            <span className="text-tally-500">{stage.index}</span>
            <span>{stage.label}</span>
          </div>
        )}
        <h1 className="display text-[1.75rem] leading-none sm:text-[2.25rem]">{title}</h1>
        {subtitle && <p className="mt-2 max-w-2xl text-sm text-graphite-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2 max-sm:w-full [&>select]:min-w-0 [&>select]:max-w-full">{actions}</div>}
    </header>
  )
}

const BADGE_TONES = {
  violet: 'text-tally-300 bg-tally-500/10 ring-tally-500/30',
  cyan: 'text-bone-200 bg-graphite-800 ring-graphite-600',
  green: 'text-ok bg-ok-dim/60 ring-ok/25',
  amber: 'text-warn bg-warn-dim/60 ring-warn/25',
  red: 'text-err bg-err-dim/60 ring-err/30',
  zinc: 'text-graphite-400 bg-graphite-850 ring-graphite-700',
} as const
export type Tone = keyof typeof BADGE_TONES

export function Badge({ tone = 'zinc', children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx('inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-[0.08em] ring-1 ring-inset', BADGE_TONES[tone], className)}>
      {children}
    </span>
  )
}

const STATUS_TONES: Record<string, Tone> = {
  ready: 'green', analyzed: 'green', completed: 'green', approved: 'green', authorized: 'green', published: 'green',
  pending: 'zinc', queued: 'zinc', unknown: 'zinc', scheduled: 'zinc', archived: 'zinc',
  copying: 'cyan', probing: 'cyan', analyzing: 'cyan', running: 'cyan', rendering: 'cyan', publishing: 'cyan',
  detected: 'violet', exported: 'violet',
  error: 'red', failed: 'red', denied: 'red', rejected: 'red',
  cancelled: 'amber', review: 'amber',
}
const LIVE = new Set(['copying', 'probing', 'analyzing', 'running', 'rendering', 'publishing'])
const STATUS_LABELS: Record<string, string> = {
  ready: 'pronto', analyzed: 'analizzato', completed: 'completato', pending: 'in attesa', queued: 'in coda',
  copying: 'copia', probing: 'lettura', analyzing: 'analisi', running: 'in corso', error: 'errore',
  failed: 'fallito', cancelled: 'annullato', detected: 'rilevata', review: 'revisione', rendering: 'rendering', approved: 'approvata', exported: 'esportata', scheduled: 'programmata', publishing: 'in pubblicazione', published: 'pubblicata', rejected: 'scartata', archived: 'archiviata', authorized: 'autorizzato', denied: 'negato', unknown: 'sconosciuto',
}

export function StatusBadge({ status }: { status: string }) {
  const tone = STATUS_TONES[status] ?? 'zinc'
  return (
    <Badge tone={tone}>
      {LIVE.has(status) && <span className="tally-dot live !h-1 !w-1 !shadow-none" />}
      {STATUS_LABELS[status] ?? status}
    </Badge>
  )
}

/** Progress as a playhead over a track: reads like a render bar, not a generic gradient pill. */
export function ProgressBar({ value, className }: { value: number; className?: string }) {
  const v = Math.max(0, Math.min(1, value))
  return (
    <div className={cx('relative h-1 w-full rounded-full bg-graphite-700', className)} role="progressbar"
         aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(v * 100)}>
      <div className="h-full rounded-full bg-tally-500 transition-[width] duration-500 ease-out" style={{ width: `${v * 100}%` }} />
      {v > 0 && v < 1 && <span className="absolute top-1/2 h-2.5 w-0.5 -translate-y-1/2 bg-bone-100" style={{ left: `calc(${v * 100}% - 1px)` }} />}
    </div>
  )
}

export function Modal(props: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  return <Dialog {...props} />
}

export function EmptyState({ icon, title, text, action }: { icon: ReactNode; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="viewfinder flex flex-col items-start justify-center px-8 py-14 sm:px-12">
      <div className="mb-5 text-tally-500">{icon}</div>
      <h3 className="display text-xl">{title}</h3>
      {text && <p className="mt-2 max-w-md text-sm text-graphite-400">{text}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  )
}

export function Spinner({ className }: { className?: string }) {
  return <span role="status" aria-label="Caricamento" className={cx('inline-block h-4 w-4 animate-spin rounded-full border-[1.5px] border-graphite-600 border-t-tally-500', className)} />
}

export function ErrorBox({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-center justify-between gap-4 border-l-2 border-err bg-err-dim/40 px-4 py-3 text-sm text-bone-200">
      <span className="flex items-center gap-2"><AlertTriangle size={15} className="shrink-0 text-err" />{error.message}</span>
      {onRetry && <button className="btn-ghost" onClick={onRetry}>Riprova</button>}
    </div>
  )
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-graphite-400">{hint}</span>}
    </label>
  )
}

/** Filter row as underline tabs with mono counts (replaces pill filters). */
export function FilterTabs<K extends string>({ value, options, onChange, label }: {
  value: K; options: { value: K; label: string; count?: number }[]; onChange: (k: K) => void; label: string
}) {
  return (
    <div role="tablist" aria-label={label} className="-mx-4 mb-5 flex overflow-x-auto border-b border-graphite-800 px-4 sm:mx-0 sm:px-0">
      {options.map((o) => {
        const active = o.value === value
        return (
          <button key={o.value || 'all'} role="tab" aria-selected={active} onClick={() => onChange(o.value)}
            className={cx('relative flex shrink-0 items-baseline gap-2 px-3 py-2.5 text-sm transition-colors first:pl-0',
              active ? 'text-bone-100' : 'text-graphite-400 hover:text-bone-200')}>
            {o.label}
            {o.count !== undefined && <span className={cx('timecode text-2xs', active ? 'text-tally-400' : 'text-graphite-500')}>{o.count}</span>}
            <span className={cx('absolute inset-x-3 -bottom-px h-0.5 bg-tally-500 transition-opacity [button:first-child>&]:left-0', active ? 'opacity-100' : 'opacity-0')} />
          </button>
        )
      })}
    </div>
  )
}
