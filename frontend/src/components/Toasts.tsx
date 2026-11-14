import { AlertTriangle, CheckCircle2, Info, X } from 'lucide-react'
import { useToasts } from '../stores/toastStore'
import { cx } from './ui'

export function Toasts() {
  const { toasts, dismiss } = useToasts()
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2">
      {toasts.map((t) => {
        const Icon = t.kind === 'success' ? CheckCircle2 : t.kind === 'error' ? AlertTriangle : Info
        return (
          <div key={t.id} role="status"
            className={cx('pointer-events-auto card flex items-start gap-3 px-4 py-3 text-sm shadow-xl',
              t.kind === 'success' && 'border-emerald-500/40',
              t.kind === 'error' && 'border-red-500/50',
              t.kind === 'info' && 'border-pulse-500/40')}>
            <Icon size={18} className={cx('mt-0.5 shrink-0',
              t.kind === 'success' ? 'text-emerald-400' : t.kind === 'error' ? 'text-red-400' : 'text-pulse-400')} />
            <span className="flex-1 text-zinc-200">{t.message}</span>
            <button onClick={() => dismiss(t.id)} className="text-zinc-500 hover:text-white" aria-label="Chiudi"><X size={14} /></button>
          </div>
        )
      })}
    </div>
  )
}
