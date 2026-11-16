import { Crosshair, ScanFace, Trash2 } from 'lucide-react'
import { useId, useRef, useState, type ReactNode } from 'react'
import { api } from '../services/api'
import { toast } from '../stores/toastStore'
import type { Layout, Region, SubtitlePreset } from '../types'
import { cx } from './ui'
import { Slider as RangeSlider } from './ui/slider'
import { Switch } from './ui/switch'

/* ------------------------------------------------------------ layout picker */
const LAYOUTS: { id: Layout; letter: string; name: string; desc: string; webcam: boolean }[] = [
  { id: 'full', letter: 'A', name: 'Full', desc: 'Gameplay a tutto schermo', webcam: false },
  { id: 'stack', letter: 'B', name: 'Stack', desc: 'Gameplay sopra, webcam sotto', webcam: true },
  { id: 'pip', letter: 'C', name: 'PiP', desc: 'Webcam picture-in-picture', webcam: true },
  { id: 'split', letter: 'D', name: 'Split', desc: 'Split 50/50 dinamico', webcam: true },
]

function Schematic({ id }: { id: Layout }) {
  const g = 'fill-bone-500/40', w = 'fill-tally-500/80'
  return (
    <svg viewBox="0 0 27 48" className="h-14 w-8 shrink-0 rounded-[3px] ring-1 ring-ink-600" aria-hidden>
      <rect width="27" height="48" className="fill-ink-800" />
      {id === 'full' && <rect width="27" height="48" className={g} />}
      {id === 'stack' && <><rect width="27" height="29" className={g} /><rect y="29.5" width="27" height="18.5" className={w} /></>}
      {id === 'pip' && <><rect width="27" height="48" className={g} /><rect x="16" y="6" width="9" height="7" rx="1.5" className={w} /></>}
      {id === 'split' && <><rect width="27" height="24" className={g} /><rect y="24.5" width="27" height="23.5" className={w} /></>}
    </svg>
  )
}

export function LayoutPicker({ value, hasWebcam, onChange }: { value: Layout; hasWebcam: boolean; onChange: (l: Layout) => void }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {LAYOUTS.map((l) => {
        const disabled = l.webcam && !hasWebcam
        return (
          <button key={l.id} onClick={() => onChange(l.id)} title={disabled ? 'Serve la regione webcam' : l.desc}
            className={cx('flex items-center gap-3 rounded-lg p-2 text-left ring-1 transition',
              value === l.id ? 'bg-graphite-850 ring-tally-500' : 'ring-graphite-700 hover:bg-graphite-850', disabled && 'opacity-50')}>
            <Schematic id={l.id} />
            <span>
              <span className="block text-sm font-semibold text-white">{l.letter} · {l.name}</span>
              <span className="block text-xs text-zinc-400">{disabled ? 'serve la webcam' : l.desc}</span>
            </span>
          </button>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------ webcam region */
export function WebcamSelector({ videoId, t, region, onSaved }: {
  videoId: string; t: number; region: Region | null; onSaved: (r: Region | null) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [draft, setDraft] = useState<Region | null>(null)
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const [reason, setReason] = useState<string | null>(null)
  const shown = draft ?? region

  const pos = (e: React.PointerEvent) => {
    const r = ref.current!.getBoundingClientRect()
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) }
  }
  const onDown = (e: React.PointerEvent) => { (e.target as Element).setPointerCapture(e.pointerId); setDragStart(pos(e)) }
  const onMove = (e: React.PointerEvent) => {
    if (!dragStart) return
    const p = pos(e)
    setDraft({ x: Math.min(p.x, dragStart.x), y: Math.min(p.y, dragStart.y), w: Math.abs(p.x - dragStart.x), h: Math.abs(p.y - dragStart.y) })
  }
  const onUp = () => {
    setDragStart(null)
    if (draft && (draft.w < 0.03 || draft.h < 0.03)) setDraft(null)
  }

  const save = async (r: Region | null) => {
    setBusy(true)
    try { const res = await api.setWebcam(videoId, r); onSaved(res.webcam_region); setDraft(null); toast.success(r ? 'Regione webcam salvata' : 'Regione webcam rimossa') }
    catch (e) { toast.error(e) } finally { setBusy(false) }
  }
  const detect = async () => {
    setBusy(true)
    try {
      const d = await api.detectWebcam(videoId)
      setReason(d.reason)
      if (d.region) { onSaved(d.saved_region); toast.success(`Webcam rilevata (confidenza ${Math.round((d.region.confidence ?? 0) * 100)}%)`) }
      else toast.info('Webcam non rilevata: disegnala a mano sul fotogramma')
    } catch (e) { toast.error(e) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-2">
      <div ref={ref} className="relative aspect-video w-full cursor-crosshair touch-none select-none overflow-hidden rounded-lg bg-black ring-1 ring-ink-600"
           onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp}>
        <img src={api.videoFrameUrl(videoId, t)} alt="Fotogramma sorgente" className="pointer-events-none h-full w-full object-contain" draggable={false} />
        {shown && (
          <div className="pointer-events-none absolute border-2 border-pulse-400 bg-pulse-400/15 shadow-[0_0_0_9999px_rgba(0,0,0,0.35)]"
               style={{ left: `${shown.x * 100}%`, top: `${shown.y * 100}%`, width: `${shown.w * 100}%`, height: `${shown.h * 100}%` }}>
            <span className="absolute -top-5 left-0 rounded bg-pulse-500 px-1 text-[10px] font-semibold text-ink-950">
              WEBCAM{shown.source === 'auto' ? ` · auto ${Math.round((shown.confidence ?? 0) * 100)}%` : draft ? ' · nuova' : ' · manuale'}
            </span>
          </div>
        )}
      </div>
      <p className="text-xs text-zinc-500">Trascina sul fotogramma per disegnare il riquadro della webcam.{reason ? ` ${reason}.` : ''}</p>
      <div className="flex flex-wrap gap-2">
        <button className="btn-cyan px-2.5 py-1.5 text-xs" onClick={detect} disabled={busy}><ScanFace size={14} /> Rileva automaticamente</button>
        {draft && <button className="btn-primary px-2.5 py-1.5 text-xs" onClick={() => save(draft)} disabled={busy}><Crosshair size={14} /> Salva regione</button>}
        {region && !draft && <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={() => save(null)} disabled={busy}><Trash2 size={14} /> Rimuovi</button>}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------ small controls */
export function Section({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="space-y-3.5 border-b border-graphite-800 pb-5 last:border-0 last:pb-0">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="eyebrow text-bone-400">{title}</h3>
        {right}
      </div>
      {children}
    </section>
  )
}

export function Toggle({ label, checked, onChange, hint }: { label: string; checked: boolean; onChange: (v: boolean) => void; hint?: string }) {
  const id = useId()
  return (
    <div className="flex items-start justify-between gap-3 py-0.5">
      <label htmlFor={id} className="cursor-pointer text-sm text-bone-200">
        {label}
        {hint && <span className="mt-0.5 block text-xs leading-snug text-graphite-400">{hint}</span>}
      </label>
      <Switch id={id} checked={checked} onCheckedChange={onChange} className="mt-0.5" />
    </div>
  )
}

export function Slider({ label, value, min, max, step, onChange, fmt }: {
  label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; fmt?: (v: number) => string
}) {
  return (
    <div className="grid grid-cols-[minmax(84px,auto)_1fr_52px] items-center gap-3 text-sm">
      <span className="text-bone-300">{label}</span>
      <RangeSlider value={[value]} min={min} max={max} step={step} onValueChange={(v) => onChange(v[0])} aria-label={label} />
      <span className="timecode text-right text-xs text-bone-200">{fmt ? fmt(value) : value}</span>
    </div>
  )
}

export function Segmented<T extends string | number>({ value, options, onChange }: {
  value: T; options: { value: T; label: string }[]; onChange: (v: T) => void
}) {
  return (
    <div className="inline-flex max-w-full flex-wrap rounded-md border border-graphite-700 bg-graphite-900 p-0.5" role="radiogroup">
      {options.map((o) => (
        <button key={String(o.value)} onClick={() => onChange(o.value)} role="radio" aria-checked={value === o.value}
          className={cx('rounded-[3px] px-2.5 py-1 text-xs font-medium transition-colors',
            value === o.value ? 'bg-graphite-700 text-bone-100 shadow-[inset_0_-2px_0_#ff5a1f]' : 'text-graphite-400 hover:text-bone-200')}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function PresetPicker({ presets, value, onChange }: { presets: SubtitlePreset[]; value: string; onChange: (id: SubtitlePreset['id']) => void }) {
  return (
    <div className="grid grid-cols-3 gap-2">
      {presets.map((p) => (
        <button key={p.id} onClick={() => onChange(p.id)}
          className={cx('rounded-md bg-[#050505] px-2 py-3 text-center ring-1 ring-inset transition', value === p.id ? 'ring-tally-500' : 'ring-graphite-700 hover:ring-graphite-500')}>
          <span className="block text-sm font-black tracking-wide" style={{ color: p.primary, WebkitTextStroke: '0.6px #000', textShadow: '0 2px 0 #000' }}>
            {p.uppercase ? 'CIAO ' : 'Ciao '}<span style={{ color: p.highlight }}>{p.uppercase ? 'RAGA' : 'raga'}</span>
          </span>
          <span className="mt-1 block text-[10px] text-zinc-400" title={p.description}>{p.name.replace('CLIPNOVA ', '')} · {p.font}</span>
        </button>
      ))}
    </div>
  )
}
