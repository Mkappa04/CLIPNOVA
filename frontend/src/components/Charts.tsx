import { useEffect, useRef, useState, type ReactNode } from 'react'

/**
 * Small, dependency-free charts for the Analytics page.
 * - one axis only, recessive grid, thin marks with 4px rounded data-ends anchored to the baseline
 * - every mark has a hover tooltip; labels use text colours, never the series colour
 */

export function useWidth<T extends HTMLElement>(min = 280) {
  const ref = useRef<T>(null)
  const [w, setW] = useState(600)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setW(Math.max(min, Math.floor(e.contentRect.width))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [min])
  return { ref, w }
}

function roundedTopBar(x: number, y: number, w: number, h: number, r = 4): string {
  if (h <= 0) return ''
  const rr = Math.min(r, w / 2, h)
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`
}

export function ColumnChart({ data, color = '#ff5a1f', height = 180, label, format = (v) => String(v) }: {
  data: { key: string; label: string; value: number }[]
  color?: string
  height?: number
  label: string
  format?: (v: number) => string
}) {
  const { ref, w } = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const M = { t: 10, r: 8, b: 22, l: 30 }
  const iw = w - M.l - M.r
  const ih = height - M.t - M.b
  const max = Math.max(1, ...data.map((d) => d.value))
  const nice = max <= 4 ? 4 : Math.ceil(max / 4) * 4  // even top → the mid gridline is a whole number
  const slot = iw / Math.max(1, data.length)
  const bw = Math.max(2, Math.min(18, slot - 2))
  const y = (v: number) => M.t + ih - (v / nice) * ih
  const every = Math.ceil(data.length / Math.max(2, Math.floor(iw / 60)))
  return (
    <div ref={ref} className="relative">
      <svg width={w} height={height} role="img" aria-label={label} onMouseLeave={() => setHover(null)}>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={M.l} x2={M.l + iw} y1={y(nice * f)} y2={y(nice * f)} stroke="#2a2a42" strokeDasharray={f === 0 ? '' : '2 4'} />
            <text x={M.l - 6} y={y(nice * f) + 3} textAnchor="end" className="fill-zinc-500 text-[10px]">{format(nice * f)}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = M.l + i * slot + (slot - bw) / 2
          return (
            <g key={d.key} onMouseEnter={() => setHover(i)}>
              <rect x={M.l + i * slot} y={M.t} width={slot} height={ih} fill="transparent" />
              <path d={roundedTopBar(x, y(d.value), bw, M.t + ih - y(d.value))} fill={color} opacity={hover === null || hover === i ? 1 : 0.45} />
              {i % every === 0 && <text x={x + bw / 2} y={height - 6} textAnchor="middle" className="fill-zinc-500 text-[10px]">{d.label}</text>}
            </g>
          )
        })}
      </svg>
      {hover !== null && data[hover] && (
        <div className="pointer-events-none absolute top-0 rounded-lg bg-ink-800/95 px-2 py-1 text-xs ring-1 ring-ink-600"
             style={{ left: Math.min(w - 140, Math.max(0, M.l + hover * slot - 40)) }}>
          <div className="text-zinc-400">{data[hover].label}</div>
          <div className="font-semibold text-zinc-100">{format(data[hover].value)} {label.toLowerCase()}</div>
        </div>
      )}
    </div>
  )
}

export function BarList({ rows, format = (v) => String(v), max: maxIn }: {
  rows: { key: string; label: ReactNode; value: number; color?: string; detail?: ReactNode }[]
  format?: (v: number) => string
  max?: number
}) {
  const max = Math.max(1, maxIn ?? Math.max(0, ...rows.map((r) => r.value)))
  return (
    <ul className="space-y-2">
      {rows.map((r) => (
        <li key={r.key} className="group" title={`${typeof r.label === 'string' ? r.label : ''} ${format(r.value)}`}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-xs">
            <span className="flex min-w-0 items-center gap-1.5 truncate text-zinc-300">
              {r.color && <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: r.color }} />}
              {r.label}
            </span>
            <span className="shrink-0 font-mono text-zinc-100">{format(r.value)}{r.detail && <span className="ml-2 text-zinc-500">{r.detail}</span>}</span>
          </div>
          <div className="h-2 rounded-full bg-ink-800">
            <div className="h-2 rounded-r-full transition-[width] duration-500 group-hover:brightness-125"
                 style={{ width: `${(r.value / max) * 100}%`, background: r.color ?? '#ff5a1f', minWidth: r.value > 0 ? 3 : 0 }} />
          </div>
        </li>
      ))}
    </ul>
  )
}
