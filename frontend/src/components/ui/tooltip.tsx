import { Tooltip as T } from 'radix-ui'
import type { ReactNode } from 'react'

export const TooltipProvider = T.Provider

export function Tip({ label, children, side = 'right' }: { label: ReactNode; children: ReactNode; side?: 'top' | 'right' | 'bottom' | 'left' }) {
  return (
    <T.Root delayDuration={250}>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content side={side} sideOffset={8}
          className="z-[60] rounded-md border border-graphite-600 bg-graphite-800 px-2 py-1 text-xs text-bone-100 shadow-pop data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0 data-[state=delayed-open]:zoom-in-95">
          {label}
        </T.Content>
      </T.Portal>
    </T.Root>
  )
}
