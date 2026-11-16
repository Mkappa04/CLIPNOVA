import { AlertTriangle, CheckCircle2, Info, X } from 'lucide-react'
import { AnimatePresence, m as motion } from 'motion/react'
import { useToasts } from '../stores/toastStore'
import { cx } from './ui'

export function Toasts() {
  const { toasts, dismiss } = useToasts()
  return (
    <div className="pointer-events-none fixed bottom-[calc(72px+env(safe-area-inset-bottom))] right-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2 md:bottom-4"
         aria-live="polite">
      <AnimatePresence initial={false}>
        {toasts.map((t) => {
          const Icon = t.kind === 'success' ? CheckCircle2 : t.kind === 'error' ? AlertTriangle : Info
          return (
            <motion.div key={t.id} role={t.kind === 'error' ? 'alert' : 'status'} layout
              initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: 24 }}
              transition={{ type: 'spring', stiffness: 600, damping: 40 }}
              className={cx('pointer-events-auto flex items-start gap-3 rounded-lg border-l-2 bg-graphite-800 py-3 pl-3.5 pr-3 text-sm shadow-pop',
                t.kind === 'success' && 'border-ok', t.kind === 'error' && 'border-err', t.kind === 'info' && 'border-bone-400')}>
              <Icon size={16} className={cx('mt-0.5 shrink-0',
                t.kind === 'success' ? 'text-ok' : t.kind === 'error' ? 'text-err' : 'text-bone-300')} />
              <span className="flex-1 text-bone-200">{t.message}</span>
              <button onClick={() => dismiss(t.id)} className="text-graphite-400 transition-colors hover:text-bone-100" aria-label="Chiudi"><X size={14} /></button>
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}
