import { Switch as S } from 'radix-ui'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

export function Switch({ className, ...p }: ComponentProps<typeof S.Root>) {
  return (
    <S.Root
      className={cn(
        'peer inline-flex h-[18px] w-8 shrink-0 cursor-pointer items-center rounded-full border border-graphite-600 bg-graphite-800 p-px transition-colors',
        'data-[state=checked]:border-tally-500 data-[state=checked]:bg-tally-500 disabled:cursor-not-allowed disabled:opacity-40',
        className,
      )}
      {...p}
    >
      <S.Thumb className="block h-3.5 w-3.5 rounded-full bg-bone-300 shadow transition-transform duration-150 ease-out data-[state=checked]:translate-x-[14px] data-[state=checked]:bg-[#160800]" />
    </S.Root>
  )
}
