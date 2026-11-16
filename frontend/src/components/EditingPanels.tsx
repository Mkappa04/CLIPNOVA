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
    <div className="grid gap-2 sm:grid-cols-3">
      {presets.filter((p) => p.id !== 'custom').map((p) => {
        const Icon = PRESET_ICON[p.id]
        const active = value === p.id
        return (
          <button key={p.id} onClick={() => onPick(p)} aria-pressed={active}
            className={cx('rounded-xl p-3 text-left ring-1 transition', active ? 'bg-nova-500/15 ring-nova-500' : 'ring-ink-600 hover:bg-ink-800')}>
            <span className="flex items-center gap-2 text-sm font-semibold text-white"><Icon size={16} className="text-pulse-300" />{p.name}</span>
            <span className="mt-1 block text-xs leading-snug text-zinc-400">{p.description}</span>
            <span className="mt-2 flex flex-wrap gap-1">
              {p.features.slice(0, 4).map((f) => <span key={f} className="rounded bg-ink-800 px-1.5 py-0.5 text-[10px] text-zinc-300">{f}</span>)}
            </span>
          </button>
        )
      })}
      {value === 'custom' && <p className="text-xs text-zinc-500 sm:col-span-3">Nessun preset attivo: impostazioni manuali (zoom solo sui picchi, nessun SFX).</p>}
    </div>
  )
}

/* ------------------------------------------------------------ plan panel */
const EFFECT_LABEL: Record<PlanEffect, string> = {
  none: 'nessun effetto', subtle_zoom: 'zoom leggero', progressive_zoom: 'zoom progressivo', punch_zoom: 'zoom rapido',
  caption_emphasis: 'enfasi sottotitolo', flash: 'flash', shake: 'shake',
}
const EFFECT_COLOR: Record<PlanEffect, string> = {
  none: 'bg-ink-700', subtle_zoom: 'bg-nova-400', progressive_zoom: 'bg-nova-600', punch_zoom: 'bg-pulse-400',
  caption_emphasis: 'bg-amber-400', flash: 'bg-white', shake: 'bg-red-400',
}

export function PlanPanel({ clipId, cfg, jobs, onJob }: {
  clipId: string; cfg: EditConfig; jobs: Job[] | null; onJob: () => void
}) {
  const [plan, setPlan] = useState<EditPlan | null>(null)
  const [stored, setStored] = useState(false)
  const [busy, setBusy] = useState(false)
  const [all, setAll] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const planJob = jobs?.find((j) => j.type === 'edit.plan' && j.payload.clip_id === clipId && ['queued', 'running'].includes(j.status))
  const lastJob = useRef<string | null>(null)

  const load = () => {
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac
    setBusy(true)
    api.planPreview(clipId, cfg, ac.signal)
      .then((r) => { setPlan(r.plan); setStored(r.stored) })
      .catch((e) => { if ((e as Error).name !== 'AbortError') toast.error(e) })
      .finally(() => { if (!ac.signal.aborted) setBusy(false) })
  }
  useEffect(() => { const h = setTimeout(load, 400); return () => clearTimeout(h) }, [clipId, JSON.stringify(cfg)]) // eslint-disable-line react-hooks/exhaustive-deps
  // reload when an AI plan job finishes
  useEffect(() => {
    if (planJob) lastJob.current = planJob.id
    else if (lastJob.current) { lastJob.current = null; load() }
  }, [planJob?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const runAi = async () => {
    try { await api.makePlan(clipId, cfg); toast.info('AI Editing Planner avviato (LLM locale)'); onJob() } catch (e) { toast.error(e) }
  }

  if (!plan) return <Spinner />
  const d = plan.duration || 1
  const fx = plan.segments.filter((s) => s.effect !== 'none')
  const shown = all ? plan.segments : fx
  const sfx = plan.segments.filter((s) => s.sfx)
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={plan.source === 'llm' ? 'cyan' : 'zinc'}>{plan.source === 'llm' ? <><Bot size={11} /> AI locale</> : 'regole'}</Badge>
        {stored && <Badge tone="green">salvato</Badge>}
        <span className="text-xs text-zinc-400">{fx.length} effetti · {plan.emphasis.length} parole evidenziate · {sfx.length} SFX
          {plan.pauses.length > 0 && ` · ${plan.pauses.filter((p) => p.action === 'cut').length} pause tagliate`}</span>
        {busy && <Spinner className="h-4 w-4" />}
        <button className="btn-cyan ml-auto px-2.5 py-1 text-xs" onClick={runAi} disabled={!!planJob || cfg.planner === 'rules'}
          title={cfg.planner === 'rules' ? 'Modalità "solo regole" attiva' : 'Ragionamento con il modello locale (Ollama)'}>
          <Sparkles size={13} /> {planJob ? 'AI in corso…' : 'Genera con AI locale'}
        </button>
      </div>

      {/* timeline */}
      <div className="relative h-7 w-full overflow-hidden rounded-md bg-ink-850 ring-1 ring-ink-700" role="img" aria-label="Timeline del piano di montaggio">
        {plan.segments.map((s, i) => (
          <div key={i} title={`${s.start.toFixed(1)}–${s.end.toFixed(1)}s · ${EFFECT_LABEL[s.effect]} · ${s.reason}`}
            className={cx('absolute top-0 h-full border-r border-ink-950/60', EFFECT_COLOR[s.effect], s.effect !== 'none' && 'opacity-90')}
            style={{ left: `${(s.start / d) * 100}%`, width: `${((s.end - s.start) / d) * 100}%`, opacity: s.effect === 'none' ? 1 : 0.35 + 0.65 * s.intensity }} />
        ))}
        {plan.pauses.filter((p) => p.action === 'cut').map((p, i) => (
          <div key={`p${i}`} className="absolute bottom-0 h-1.5 bg-red-500/70" title={`Pausa tagliata ${p.start.toFixed(1)}–${p.end.toFixed(1)}s`}
            style={{ left: `${(p.start / d) * 100}%`, width: `${((p.end - p.start) / d) * 100}%` }} />
        ))}
        {plan.emphasis.map((w, i) => (
          <div key={`e${i}`} className="absolute top-0 h-2 w-0.5 bg-amber-300" title={`Parola evidenziata: ${w.word}`} style={{ left: `${(w.start / d) * 100}%` }} />
        ))}
        {sfx.map((s, i) => (
          <span key={`s${i}`} className="absolute bottom-0 text-[10px] leading-none" title={`SFX ${s.sfx!.category}`} style={{ left: `${(s.sfx!.at / d) * 100}%` }}>♪</span>
        ))}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-zinc-400">
        {(['subtle_zoom', 'progressive_zoom', 'punch_zoom', 'caption_emphasis', 'flash', 'shake'] as PlanEffect[]).map((e) => (
          <span key={e} className="flex items-center gap-1"><span className={cx('h-2 w-2 rounded-sm', EFFECT_COLOR[e])} />{EFFECT_LABEL[e]}</span>
        ))}
        <span className="flex items-center gap-1"><span className="h-1.5 w-2 bg-red-500/70" />pausa tagliata</span>
      </div>

      {/* decisions */}
      <ul className="max-h-56 space-y-1 overflow-auto text-xs">
        {shown.length === 0 && <li className="text-zinc-400">Nessun effetto: il planner ha scelto di lasciare il video naturale.</li>}
        {shown.map((s, i) => (
          <li key={i} className="flex gap-2 rounded bg-ink-850 px-2 py-1">
            <span className="w-20 shrink-0 font-mono text-zinc-500">{s.start.toFixed(1)}–{s.end.toFixed(1)}s</span>
            <span className={cx('w-28 shrink-0 font-semibold', s.effect === 'none' ? 'text-zinc-500' : 'text-white')}>
              {EFFECT_LABEL[s.effect]}{s.effect !== 'none' && ` ${Math.round(s.intensity * 100)}%`}{s.sfx && ` ♪${s.sfx.category}`}
            </span>
            <span className="text-zinc-400">{s.reason}</span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <button className="text-pulse-400 hover:underline" onClick={() => setAll(!all)}>{all ? 'Solo effetti' : 'Mostra anche i tratti senza effetto'}</button>
        {plan.emphasis.length > 0 && <span className="text-zinc-400">Evidenziate: {plan.emphasis.map((w) => w.word).join(', ')}</span>}
      </div>
      {plan.notes.length > 0 && <p className="text-[11px] text-zinc-500">{plan.notes.slice(0, 3).join(' · ')}</p>}
    </div>
  )
}
