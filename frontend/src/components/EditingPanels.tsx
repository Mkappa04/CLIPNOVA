import { Bot, Gamepad2, Mic, Sparkles, Trophy, Wand2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../services/api'
import { toast } from '../stores/toastStore'
import type { EditConfig, EditingPreset, EditingPresetId, EditPlan, Job, PlanEffect } from '../types'
import { Badge, Spinner, cx } from './ui'

/* ------------------------------------------------------------ preset picker */
const PRESET_ICON: Record<EditingPresetId, typeof Gamepad2> = {
  gaming_dynamic: Gamepad2, sports_highlights: Trophy, podcast_clean: Mic, custom: Wand2,
}

export function EditingPresetPicker({ presets, value, onPick }: {
  presets: EditingPreset[]; value: EditingPresetId; onPick: (p: EditingPreset) => void
}) {
  return (
    <div className="divide-y divide-graphite-800 border-y border-graphite-800">
      {presets.filter((p) => p.id !== 'custom').map((p) => {
        const Icon = PRESET_ICON[p.id]
        const active = value === p.id
        return (
          <button key={p.id} onClick={() => onPick(p)} aria-pressed={active}
            className={cx('group relative grid w-full grid-cols-[2rem_1fr] gap-3 py-3.5 pl-3 pr-2 text-left transition-colors', active ? 'bg-graphite-850' : 'hover:bg-graphite-900')}>
            <span className={cx('absolute inset-y-2 left-0 w-0.5 rounded-full bg-tally-500 transition-opacity', active ? 'opacity-100' : 'opacity-0')} />
            <Icon size={18} strokeWidth={1.75} className={cx('mt-0.5', active ? 'text-tally-500' : 'text-graphite-400 group-hover:text-bone-300')} />
            <span className="min-w-0">
              <span className="display block text-[15px]">{p.name}</span>
              <span className="mt-1 block text-xs leading-snug text-graphite-400">{p.description}</span>
              <span className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
                {p.features.slice(0, 4).map((f) => <span key={f} className="font-mono text-[10px] uppercase tracking-wider text-bone-500">{f}</span>)}
              </span>
            </span>
          </button>
        )
      })}
      {value === 'custom' && <p className="py-3 text-xs text-graphite-400">Nessun preset attivo: impostazioni manuali (zoom solo sui picchi, nessun SFX).</p>}
    </div>
  )
}

/* ------------------------------------------------------------ plan panel */
export const EFFECT_LABEL: Record<PlanEffect, string> = {
  none: 'nessun effetto', subtle_zoom: 'zoom leggero', progressive_zoom: 'zoom progressivo', punch_zoom: 'zoom rapido',
  caption_emphasis: 'enfasi sottotitolo', flash: 'flash', shake: 'shake',
}
export const EFFECT_COLOR: Record<PlanEffect, string> = {
  none: 'bg-graphite-700', subtle_zoom: 'bg-tally-300', progressive_zoom: 'bg-tally-400', punch_zoom: 'bg-tally-500',
  caption_emphasis: 'bg-warn', flash: 'bg-bone-100', shake: 'bg-err',
}

/** Rules-only plan for the current (possibly unsaved) config, the stored AI plan when it still matches. */
export function usePlanPreview(clipId: string | null, cfg: EditConfig | null, jobs: Job[] | null) {
  const [plan, setPlan] = useState<EditPlan | null>(null)
  const [stored, setStored] = useState(false)
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const planJob = jobs?.find((j) => j.type === 'edit.plan' && j.payload.clip_id === clipId && ['queued', 'running'].includes(j.status)) ?? null
  const lastJob = useRef<string | null>(null)
  const key = cfg ? JSON.stringify(cfg) : ''

  const load = () => {
    if (!clipId || !cfg) return
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac
    setBusy(true)
    api.planPreview(clipId, cfg, ac.signal)
      .then((r) => { setPlan(r.plan); setStored(r.stored) })
      .catch((e) => { if ((e as Error).name !== 'AbortError') toast.error(e) })
      .finally(() => { if (!ac.signal.aborted) setBusy(false) })
  }
  useEffect(() => { setPlan(null) }, [clipId])
  useEffect(() => { const h = setTimeout(load, 400); return () => clearTimeout(h) }, [clipId, key]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (planJob) lastJob.current = planJob.id
    else if (lastJob.current) { lastJob.current = null; load() }
  }, [planJob?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  return { plan, stored, busy, planJob }
}

/** Plan as a scrub bar under the monitor: click/drag to move the preview, effects as coloured spans. */
export function PlanStrip({ plan, duration, t, onSeek }: { plan: EditPlan | null; duration: number; t: number; onSeek: (t: number) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const d = plan?.duration || duration || 1
  const seek = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect()
    onSeek(Math.max(0, Math.min(d - 0.05, ((clientX - r.left) / r.width) * d)))
  }
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowLeft') { e.preventDefault(); onSeek(Math.max(0, t - (e.shiftKey ? 2 : 0.5))) }
    if (e.key === 'ArrowRight') { e.preventDefault(); onSeek(Math.min(d - 0.05, t + (e.shiftKey ? 2 : 0.5))) }
  }
  const ticks = Array.from({ length: Math.floor(d) + 1 }, (_, i) => i)
  return (
    <div className="select-none">
      <div ref={ref} role="slider" tabIndex={0} aria-label="Posizione nella clip" aria-valuemin={0} aria-valuemax={Math.round(d * 10) / 10}
        aria-valuenow={Math.round(t * 10) / 10} aria-valuetext={`${t.toFixed(1)} secondi`} onKeyDown={onKey}
        onPointerDown={(e) => { (e.target as Element).setPointerCapture(e.pointerId); seek(e.clientX) }}
        onPointerMove={(e) => { if (e.buttons === 1) seek(e.clientX) }}
        className="relative h-10 cursor-ew-resize overflow-hidden rounded-sm bg-graphite-850 ring-1 ring-inset ring-graphite-700">
        {/* second ticks */}
        {ticks.map((i) => (
          <span key={i} className={cx('absolute bottom-0 w-px bg-graphite-600', i % 5 === 0 ? 'h-2.5' : 'h-1')} style={{ left: `${(i / d) * 100}%` }} />
        ))}
        {plan?.segments.filter((s) => s.effect !== 'none').map((s, i) => (
          <span key={i} title={`${EFFECT_LABEL[s.effect]} · ${s.reason}`}
            className={cx('absolute top-1.5 h-4 rounded-[2px]', EFFECT_COLOR[s.effect])}
            style={{ left: `${(s.start / d) * 100}%`, width: `${((s.end - s.start) / d) * 100}%`, opacity: 0.45 + 0.55 * s.intensity }} />
        ))}
        {plan?.pauses.filter((p) => p.action === 'cut').map((p, i) => (
          <span key={`p${i}`} className="absolute top-[26px] h-1 bg-err/70" style={{ left: `${(p.start / d) * 100}%`, width: `${((p.end - p.start) / d) * 100}%` }} />
        ))}
        {plan?.emphasis.map((w, i) => (
          <span key={`e${i}`} className="absolute top-1.5 h-1.5 w-px bg-warn" style={{ left: `${(w.start / d) * 100}%` }} />
        ))}
        {/* playhead */}
        <span className="pointer-events-none absolute inset-y-0 w-px bg-tally-500" style={{ left: `${(t / d) * 100}%` }}>
          <span className="absolute -left-[4px] -top-px h-0 w-0 border-x-[4.5px] border-t-[6px] border-x-transparent border-t-tally-500" />
        </span>
      </div>
    </div>
  )
}

export function PlanPanel({ clipId, cfg, plan, stored, busy, planJob, onJob }: {
  clipId: string; cfg: EditConfig; plan: EditPlan | null; stored: boolean; busy: boolean; planJob: Job | null; onJob: () => void
}) {
  const [all, setAll] = useState(false)
  const runAi = async () => {
    try { await api.makePlan(clipId, cfg); toast.info('AI Editing Planner avviato (LLM locale)'); onJob() } catch (e) { toast.error(e) }
  }
  if (!plan) return <Spinner />
  const fx = plan.segments.filter((s) => s.effect !== 'none')
  const shown = all ? plan.segments : fx
  const sfx = plan.segments.filter((s) => s.sfx)
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={plan.source === 'llm' ? 'violet' : 'zinc'}>{plan.source === 'llm' ? <><Bot size={11} /> AI locale</> : 'regole'}</Badge>
        {stored && <Badge tone="green">salvato</Badge>}
        {busy && <Spinner className="h-3.5 w-3.5" />}
        <button className="btn-cyan ml-auto px-2.5 py-1.5 text-xs" onClick={runAi} disabled={!!planJob || cfg.planner === 'rules'}
          title={cfg.planner === 'rules' ? 'Modalità "solo regole" attiva' : 'Ragionamento con il modello locale (Ollama), ~40 s'}>
          <Sparkles size={13} /> {planJob ? 'AI in corso…' : 'Genera con AI locale'}
        </button>
      </div>

      <dl className="grid grid-cols-4 divide-x divide-graphite-800 border-y border-graphite-800 text-center">
        {[['Effetti', fx.length], ['Parole', plan.emphasis.length], ['SFX', sfx.length], ['Pause tagliate', plan.pauses.filter((p) => p.action === 'cut').length]].map(([k, v]) => (
          <div key={k} className="py-2.5"><dt className="eyebrow">{k}</dt><dd className="timecode mt-1 text-lg text-bone-100">{v}</dd></div>
        ))}
      </dl>

      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-graphite-400">
        {(['subtle_zoom', 'progressive_zoom', 'punch_zoom', 'caption_emphasis', 'flash', 'shake'] as PlanEffect[]).map((e) => (
          <span key={e} className="flex items-center gap-1.5"><span className={cx('h-2 w-2 rounded-[1px]', EFFECT_COLOR[e])} />{EFFECT_LABEL[e]}</span>
        ))}
        <span className="flex items-center gap-1.5"><span className="h-1 w-2.5 bg-err/70" />pausa tagliata</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-px bg-warn" />parola evidenziata</span>
      </div>

      <ol className="max-h-72 divide-y divide-graphite-800 overflow-auto border-y border-graphite-800 text-xs">
        {shown.length === 0 && <li className="py-3 text-graphite-400">Nessun effetto: il planner ha scelto di lasciare il video naturale.</li>}
        {shown.map((s, i) => (
          <li key={i} className="grid grid-cols-[5.5rem_7.5rem_1fr] gap-3 py-2">
            <span className="timecode text-graphite-400">{s.start.toFixed(1)}–{s.end.toFixed(1)}s</span>
            <span className={cx('flex items-center gap-1.5 font-medium', s.effect === 'none' ? 'text-graphite-400' : 'text-bone-100')}>
              <span className={cx('h-2 w-2 shrink-0 rounded-[1px]', EFFECT_COLOR[s.effect])} />
              {EFFECT_LABEL[s.effect]}{s.effect !== 'none' && <span className="timecode text-graphite-400">{Math.round(s.intensity * 100)}</span>}
              {s.sfx && <span className="text-warn">♪</span>}
            </span>
            <span className="text-graphite-400">{s.reason}</span>
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <button className="link" onClick={() => setAll(!all)}>{all ? 'Solo effetti' : 'Mostra anche i tratti senza effetto'}</button>
        {plan.emphasis.length > 0 && <span className="text-graphite-400">Evidenziate: <span className="text-bone-300">{plan.emphasis.map((w) => w.word).join(', ')}</span></span>}
      </div>
      {plan.notes.length > 0 && <p className="text-[11px] text-graphite-500">{plan.notes.slice(0, 3).join(' · ')}</p>}
    </div>
  )
}
