import { Dialog as D } from 'radix-ui'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** Accessible modal (focus trap, Esc, scroll lock) used by the legacy `Modal` API. */
export function Dialog({ open, onClose, title, children, wide }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean
}) {
  return (
    <D.Root open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-50 bg-black/75 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <D.Content
          aria-describedby={undefined}
          className={cn(
            'fixed inset-x-0 bottom-0 z-50 max-h-[92dvh] overflow-y-auto border-t border-graphite-600 bg-graphite-900 shadow-pop outline-none',
            'sm:inset-x-auto sm:bottom-auto sm:left-1/2 sm:top-[8vh] sm:max-h-[84vh] sm:w-[calc(100%-2rem)] sm:-translate-x-1/2 sm:rounded-lg sm:border',
            'data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-bottom-4 sm:data-[state=open]:slide-in-from-bottom-2',
            wide ? 'sm:max-w-4xl' : 'sm:max-w-xl',
          )}
        >
          <div className="sticky top-0 z-10 flex items-center justify-between border-b border-graphite-700 bg-graphite-900 px-5 py-3.5">
            <D.Title className="display text-base">{title}</D.Title>
            <D.Close className="rounded-md p-1 text-graphite-400 transition-colors hover:bg-graphite-800 hover:text-bone-100" aria-label="Chiudi">
              <X size={18} />
            </D.Close>
          </div>
          <div className="p-5">{children}</div>
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}
