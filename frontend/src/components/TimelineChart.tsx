import { useEffect, useMemo, useRef, useState } from 'react'
import { CATEGORY_BY_ID, formatDuration, formatTime } from '../services/format'
import type { Clip, TimelineData } from '../types'

/**
 * Interest-over-time chart for one video.
 * - single series (interest, 0..1) drawn as a 2px line + light area
 * - detected clips as category-coloured spans (identity also in the legend + clip list)
 * - scene cuts as recessive ticks, speech presence as a thin strip
 * - hover: crosshair + tooltip; click on a clip span selects it
 */
const H = 190
const M = { top: 14, right: 12, bottom: 26, left: 34 }
const SPEECH_H = 6

export function TimelineChart({ timeline, duration, clips, selectedId, onSelect }: {
  timeline: TimelineData
  duration: number
  clips: Clip[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(800)
  const [hover, setHover] = useState<{ x: number; t: number } | null>(null)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(320, Math.floor(e.contentRect.width))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const innerW = width - M.left - M.right
  const plotH = H - M.top - M.bottom - SPEECH_H - 6
  const total = Math.max(duration, timeline.interest.length * timeline.step_s, 1)
  const x = (t: number) => M.left + (t / total) * innerW
  const y = (v: number) => M.top + (1 - Math.max(0, Math.min(1, v))) * plotH

  const { line, area } = useMemo(() => {
    const pts = timeline.interest.map((v, i) => `${x(i * timeline.step_s).toFixed(1)},${y(v).toFixed(1)}`)
    if (!pts.length) return { line: '', area: '' }
    const line = `M${pts.join('L')}`
    const area = `${line}L${x((timeline.interest.length - 1) * timeline.step_s).toFixed(1)},${y(0)}L${x(0)},${y(0)}Z`
    return { line, area }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeline, width, total])

  const ticks = useMemo(() => {
    const target = Math.max(3, Math.floor(innerW / 110))
    const steps = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600]
    const step = steps.find((s) => total / s <= target) ?? 3600
    const out: number[] = []
    for (let t = 0; t <= total + 0.01; t += step) out.push(t)
    return out
  }, [innerW, total])

  const speechTop = M.top + plotH + 6
  const idx = hover ? Math.min(timeline.interest.length - 1, Math.max(0, Math.round(hover.t / timeline.step_s))) : 0
  const hoverClip = hover ? clips.find((c) => hover.t >= c.start && hover.t <= c.end) : undefined

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - rect.left
    if (px < M.left || px > M.left + innerW) return setHover(null)
    setHover({ x: px, t: ((px - M.left) / innerW) * total })
  }

  return (
    <div ref={wrapRef} className="relative w-full select-none">
      <svg width={width} height={H} onMouseMove={onMove} onMouseLeave={() => setHover(null)}
           onClick={() => hoverClip && onSelect(hoverClip.id)}
           className={hoverClip ? 'cursor-pointer' : 'cursor-crosshair'} role="img"
           aria-label="Andamento dell'interesse stimato nel video con le clip rilevate">
        {/* recessive grid */}
        {[0, 0.5, 1].map((v) => (
          <g key={v}>
            <line x1={M.left} x2={M.left + innerW} y1={y(v)} y2={y(v)} stroke="#2a2a42" strokeWidth={1} strokeDasharray={v === 0 ? '' : '2 4'} />
            <text x={M.left - 6} y={y(v) + 3} textAnchor="end" className="fill-zinc-500 text-[10px]">{v === 0 ? '0' : v === 1 ? '1' : '.5'}</text>
          </g>
        ))}

        {/* clip spans */}
        {clips.map((c) => {
          const cat = CATEGORY_BY_ID[c.category]
          const sel = c.id === selectedId
          const x0 = x(c.start), w = Math.max(2, x(c.end) - x0)
          return (
            <g key={c.id}>
              <rect x={x0} y={M.top} width={w} height={plotH} fill={cat?.color} opacity={sel ? 0.28 : 0.14} />
              <rect x={x0} y={M.top - 4} width={w} height={4} rx={2} fill={cat?.color} />
              {sel && <rect x={x0} y={M.top} width={w} height={plotH} fill="none" stroke="#f0efec" strokeWidth={1.5} />}
            </g>
          )
        })}

        {/* scene cuts */}
        {timeline.scenes.map((t) => (
          <line key={t} x1={x(t)} x2={x(t)} y1={M.top + plotH - 8} y2={M.top + plotH} stroke="#6b6b80" strokeWidth={1} />
        ))}

        {/* interest series */}
        <path d={area} fill="#22d3ee" opacity={0.12} />
        <path d={line} fill="none" stroke="#22d3ee" strokeWidth={2} strokeLinejoin="round" />

        {/* speech strip */}
        <text x={M.left - 6} y={speechTop + SPEECH_H} textAnchor="end" className="fill-zinc-500 text-[9px]">voce</text>
        <rect x={M.left} y={speechTop} width={innerW} height={SPEECH_H} rx={2} fill="#141422" />
        {timeline.speech.map((v, i) => v > 0.2 && (
          <rect key={i} x={x(i * timeline.step_s)} y={speechTop} height={SPEECH_H}
                width={Math.max(1, (timeline.step_s / total) * innerW)} fill="#8b8b9e" opacity={0.7} />
        ))}

        {/* x axis */}
        {ticks.map((t) => (
          <text key={t} x={x(t)} y={H - 8} textAnchor="middle" className="fill-zinc-500 text-[10px]">{formatDuration(t)}</text>
        ))}

        {/* hover crosshair */}
        {hover && (
          <g pointerEvents="none">
            <line x1={hover.x} x2={hover.x} y1={M.top} y2={speechTop + SPEECH_H} stroke="#c3c2b7" strokeWidth={1} strokeDasharray="3 3" />
            <circle cx={hover.x} cy={y(timeline.interest[idx] ?? 0)} r={4} fill="#22d3ee" stroke="#0a0a12" strokeWidth={2} />
          </g>
        )}
      </svg>

      {hover && (
        <div className="pointer-events-none absolute top-0 z-10 rounded-lg bg-ink-800/95 px-2.5 py-1.5 text-xs shadow-lg ring-1 ring-ink-600"
             style={{ left: Math.min(hover.x + 12, width - 190) }}>
          <div className="font-mono text-zinc-100">{formatTime(hover.t)}</div>
          <div className="text-zinc-400">Interesse <span className="text-zinc-100">{(timeline.interest[idx] ?? 0).toFixed(2)}</span></div>
          {hoverClip && (
            <div className="mt-1 flex items-center gap-1.5 text-zinc-200">
              <span className="h-2 w-2 rounded-full" style={{ background: CATEGORY_BY_ID[hoverClip.category]?.color }} />
              {CATEGORY_BY_ID[hoverClip.category]?.label} · score {hoverClip.score.toFixed(0)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function CategoryLegend({ categories }: { categories: string[] }) {
  if (!categories.length) return null
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-400">
      <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded bg-pulse-400" /> Interesse stimato</span>
      {categories.map((id) => (
        <span key={id} className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: CATEGORY_BY_ID[id]?.color }} />
          {CATEGORY_BY_ID[id]?.label ?? id}
        </span>
      ))}
      <span className="flex items-center gap-1.5"><span className="h-2.5 w-px bg-zinc-500" /> Cambio scena</span>
    </div>
  )
}

export function CategoryBadge({ category }: { category: string }) {
  const c = CATEGORY_BY_ID[category]
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-ink-800 px-2 py-0.5 text-[11px] font-semibold text-zinc-200 ring-1 ring-ink-600">
      <span className="h-2 w-2 rounded-full" style={{ background: c?.color }} />
      {c ? `${c.emoji} ${c.label}` : category}
    </span>
  )
}
