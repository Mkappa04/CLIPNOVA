import { Slider as S } from 'radix-ui'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

export function Slider({ className, ...p }: ComponentProps<typeof S.Root>) {
  return (
    <S.Root className={cn('relative flex h-5 w-full touch-none select-none items-center', className)} {...p}>
      <S.Track className="relative h-[3px] grow overflow-hidden rounded-full bg-graphite-700">
        <S.Range className="absolute h-full bg-tally-500" />
      </S.Track>
      <S.Thumb
        className="block h-3.5 w-3.5 rounded-sm border border-tally-500 bg-graphite-950 shadow transition-transform hover:scale-110 focus-visible:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-tally-500/50"
      />
    </S.Root>
  )
}
