import { Tabs as T } from 'radix-ui'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

export const Tabs = T.Root

/** Underline tabs (horizontal) or a left rail (vertical), like the panels of an editing app. */
export function TabsList({ className, ...p }: ComponentProps<typeof T.List>) {
  return (
    <T.List
      className={cn(
        'flex gap-1 border-b border-graphite-700 data-[orientation=vertical]:flex-col data-[orientation=vertical]:border-b-0 data-[orientation=vertical]:border-r',
        className,
      )}
      {...p}
    />
  )
}

export function TabsTrigger({ className, ...p }: ComponentProps<typeof T.Trigger>) {
  return (
    <T.Trigger
      className={cn(
        'relative inline-flex items-center gap-2 whitespace-nowrap px-3 py-2 text-sm font-medium text-graphite-400 outline-none transition-colors',
        'hover:text-bone-200 data-[state=active]:text-bone-100',
        // active marker: a tally bar under (horizontal) or beside (vertical) the label
        "after:absolute after:inset-x-3 after:-bottom-px after:h-0.5 after:bg-tally-500 after:opacity-0 after:transition-opacity data-[state=active]:after:opacity-100",
        'data-[orientation=vertical]:w-full data-[orientation=vertical]:justify-start data-[orientation=vertical]:after:inset-x-auto data-[orientation=vertical]:after:-right-px data-[orientation=vertical]:after:inset-y-1.5 data-[orientation=vertical]:after:h-auto data-[orientation=vertical]:after:w-0.5',
        'data-[orientation=vertical]:data-[state=active]:bg-graphite-850',
        className,
      )}
      {...p}
    />
  )
}

export function TabsContent({ className, ...p }: ComponentProps<typeof T.Content>) {
  return <T.Content className={cn('outline-none data-[state=active]:animate-in data-[state=active]:fade-in-0', className)} {...p} />
}
