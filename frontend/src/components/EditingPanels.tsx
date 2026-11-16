import { BookOpen, Bot, Clapperboard, Gamepad2, Mic, Music2, Sparkles, Trophy, Wand2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../services/api'
import { toast } from '../stores/toastStore'
import type { EditConfig, EditingPreset, EditingPresetId, EditPlan, Job, MomentType, PlanEffect, PlanStyle } from '../types'
import { Badge, Spinner, cx } from './ui'

/* ------------------------------------------------------------ preset picker */
const PRESET_ICON: Record<EditingPresetId, typeof Gamepad2> = {
  gaming_dynamic: Gamepad2, gaming_cinematic: Clapperboard, sports_highlights: Trophy, podcast_clean: Mic,
  storytelling: BookOpen, custom: Wand2,
}

export function EditingPresetPicker({ presets, value, onPick }: {
  presets: EditingPreset[]; value: EditingPresetId; onPick: (p: EditingPreset) => void
}) {
  return (
    <div className="divide-y divide-graphite-800 border-y border-graphite-800">
      {presets.filter((p) => p.id !== 'custom').map((p) => {
        const Icon = PRESET_ICON[p.id] ?? Wand2
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
                {p.features.slice(0, 5).map((f) => <span key={f} className="font-mono text-[10px] uppercase tracking-wider text-bone-500">{f}</span>)}
              </span>
            </span>
          </button>
        )
      })}
      {value === 'custom' && <p className="py-3 text-xs text-graphite-400">Nessun preset attivo: impostazioni manuali (zoom solo sui picchi, nessun SFX, niente musica).</p>}
    </div>
  )
}

/* ------------------------------------------------------------ labels */
export const EFFECT_LABEL: Record<PlanEffect, string> = {
  none: 'nessun effetto', subtle_zoom: 'zoom leggero', progressive_zoom: 'zoom progressivo', punch_zoom: 'zoom rapido',
  caption_emphasis: 'enfasi sottotitolo', flash: 'flash', shake: 'camera shake', glitch: 'glitch',
}
export const EFFECT_COLOR: Record<PlanEffect, string> = {
  none: 'bg-graphite-700', subtle_zoom: 'bg-tally-300', progressive_zoom: 'bg-tally-400', punch_zoom: 'bg-tally-500',
  caption_emphasis: 'bg-warn', flash: 'bg-bone-100', shake: 'bg-err', glitch: 'bg-cyan-400',
}
const TIME_LABEL = { slow_motion: 'slow motion', speed_ramp: 'speed ramp', freeze_frame: 'fermo immagine' } as const
const TRANSITION_LABEL = { crossfade: 'dissolvenza', zoom_blur: 'zoom blur', flash: 'flash', glitch: 'glitch', dip: 'passaggio al nero' } as const
export const STYLE_LABEL: Record<PlanStyle, string> = { minimal: 'minimale', balanced: 'equilibrato', energetic: 'energico', cinematic: 'cinematografico' }
export const MOMENT_LABEL: Record<MomentType, string> = {
  funny: 'divertente', spectacular: 'spettacolare', competitive: 'competitivo', narrative: 'narrativo', emotional: 'emozionante',
  informative: 'informativo', tension: 'tensione', action_only: 'solo movimento',
}
export const MOOD_LABEL: Record<string, string> = {
  cinematic: 'cinematografica', dynamic: 'dinamica', electronic: 'elettronica', chill: 'rilassata', dramatic: 'drammatica', gaming: 'gaming',
}

type Track = 'fx' | 'time' | 'cut' | 'text' | 'audio' | 'global'
export interface PlanItem { id: string; track: Track; start: number; end: number; label: string; reason: string; color: string; value?: string }

/** Every switchable decision of the plan, in time order. */
export function planItems(plan: EditPlan): PlanItem[] {
  const items: PlanItem[] = []
  for (const s of plan.segments.filter((x) => x.effect !== 'none'))
    items.push({ id: s.id, track: 'fx', start: s.start, end: s.end, label: EFFECT_LABEL[s.effect], reason: s.reason, color: EFFECT_COLOR[s.effect], value: `${Math.round(s.intensity * 100)}%` })
  for (const e of plan.time_effects ?? [])
    items.push({ id: e.id, track: 'time', start: e.start, end: e.kind === 'freeze_frame' ? e.start + 0.15 : e.end, label: TIME_LABEL[e.kind], reason: e.reason, color: 'bg-violet-400',
      value: e.kind === 'freeze_frame' ? `${e.hold.toFixed(1)} s` : `${Math.round(e.speed * 100)}%` })
  for (const t of plan.transitions ?? [])
    items.push({ id: t.id, track: 'cut', start: t.at, end: t.at + 0.15, label: TRANSITION_LABEL[t.kind], reason: t.reason, color: 'bg-sky-400', value: t.sfx ? `♪ ${t.sfx.category}` : undefined })
  for (const o of plan.overlays ?? [])
    items.push({ id: o.id, track: 'text', start: o.start, end: o.end, label: o.kind === 'hook_title' ? 'titolo' : 'scritta', reason: `${o.reason} · ${o.evidence}`, color: 'bg-emerald-400', value: `“${o.text}”` })
  for (const c of plan.sounds ?? [])
    items.push({ id: c.id, track: 'audio', start: c.at, end: c.at + 0.15, label: `suono ${c.category.replace('_', ' ')}`, reason: c.reason, color: 'bg-warn' })
  return items.sort((a, b) => a.start - b.start)
}

/** Rules-only plan for the current (possibly unsaved) config, the stored AI plan when it still matches. */
export function usePlanPreview(clipId: string | null, cfg: EditConfig | null, jobs: Job[] | null) {
  const [plan, setPlan] = useState<EditPlan | null>(null)
  const [stored, setStored] = useState(false)
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const planJob = jobs?.find((j) => j.type === 'edit.plan' && j.payload.clip_id === clipId && ['queued', 'running'].includes(j.status)) ?? null
  const lastJob = useRef<string | null>(null)
  // the user's on/off switches do not change the plan itself (the renderer drops those items)
  const key = cfg ? JSON.stringify({ ...cfg, disabled_items: [] }) : ''

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

const TRACKS: { id: Track; label: string }[] = [
  { id: 'fx', label: 'FX' }, { id: 'time', label: 'Tempo' }, { id: 'cut', label: 'Tagli' }, { id: 'text', label: 'Testi' }, { id: 'audio', label: 'Suoni' },
]

/** Plan as a multi-track scrub bar under the monitor: click/drag to move the preview. */
export function PlanStrip({ plan, duration, t, onSeek, disabled = [] }: {
  plan: EditPlan | null; duration: number; t: number; onSeek: (t: number) => void; disabled?: string[]
}) {
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
  const items = plan ? planItems(plan) : []
  const pct = (x: number) => `${(x / d) * 100}%`
  return (
    <div className="grid select-none grid-cols-[2.6rem_1fr] gap-x-2">
      <div className="flex flex-col justify-between py-1 font-mono text-[9px] uppercase tracking-wider text-graphite-500" aria-hidden>
        {TRACKS.map((tr) => <span key={tr.id} className="leading-[10px]">{tr.label}</span>)}
        <span className="leading-[10px]">♪</span>
      </div>
      <div ref={ref} role="slider" tabIndex={0} aria-label="Posizione nella clip" aria-valuemin={0} aria-valuemax={Math.round(d * 10) / 10}
        aria-valuenow={Math.round(t * 10) / 10} aria-valuetext={`${t.toFixed(1)} secondi`} onKeyDown={onKey}
        onPointerDown={(e) => { (e.target as Element).setPointerCapture(e.pointerId); seek(e.clientX) }}
        onPointerMove={(e) => { if (e.buttons === 1) seek(e.clientX) }}
        className="relative h-[76px] cursor-ew-resize overflow-hidden rounded-sm bg-graphite-850 ring-1 ring-inset ring-graphite-700">
        {Array.from({ length: Math.floor(d) + 1 }, (_, i) => (
          <span key={i} className={cx('absolute bottom-0 w-px bg-graphite-700', i % 5 === 0 ? 'h-full opacity-60' : 'h-1')} style={{ left: pct(i) }} />
        ))}
        {plan?.pauses.filter((p) => p.action === 'cut').map((p, i) => (
          <span key={`p${i}`} className="absolute top-[26px] h-[10px] bg-err/35" style={{ left: pct(p.start), width: pct(p.end - p.start) }} title="pausa tagliata" />
        ))}
        {items.map((it) => {
          const row = TRACKS.findIndex((tr) => tr.id === it.track)
          return (
            <span key={it.id} title={`${it.label} · ${it.reason}`}
              className={cx('absolute h-[10px] rounded-[2px]', it.color, disabled.includes(it.id) && 'opacity-20')}
              style={{ top: 4 + row * 12, left: pct(it.start), width: `max(3px, ${pct(it.end - it.start)})` }} />
          )
        })}
        {plan?.emphasis.map((w, i) => <span key={`e${i}`} className="absolute top-[4px] h-[10px] w-px bg-warn" style={{ left: pct(w.start) }} />)}
        {plan?.music && (
          <span className={cx('absolute left-0 right-0 top-[64px] h-[6px] rounded-[2px] bg-gradient-to-r from-violet-500/30 via-violet-400/60 to-violet-500/30',
            disabled.includes('music') && 'opacity-20')} title={`Musica: ${plan.music.title}`}>
            {plan.music.sync_at != null && <span className="absolute -top-1 h-[14px] w-0.5 bg-violet-200" style={{ left: pct(plan.music.sync_at) }} title="beat sul culmine" />}
          </span>
        )}
        <span className="pointer-events-none absolute inset-y-0 w-px bg-tally-500" style={{ left: pct(t) }}>
          <span className="absolute -left-[4px] -top-px h-0 w-0 border-x-[4.5px] border-t-[6px] border-x-transparent border-t-tally-500" />
        </span>
      </div>
    </div>
  )
}

/** What the Director understood about the clip. */
export function DirectorSummary({ plan }: { plan: EditPlan }) {
  const d = plan.director
  if (!d) return null
  const pct = (x: number) => `${Math.round(x * 100)}%`
  const moments = d.moments.filter((m) => m.strength >= 0.35)
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 divide-graphite-800 border-y border-graphite-800 text-center sm:grid-cols-4 sm:divide-x">
        {[['Stile', STYLE_LABEL[d.style]], ['Energia', pct(d.energy)], ['Comprensibile', pct(d.comprehensibility)], ['Parlato', pct(d.speech_coverage)]].map(([k, v]) => (
          <div key={k} className="py-2.5"><dt className="eyebrow">{k}</dt><dd className="timecode mt-1 text-base text-bone-100">{v}</dd></div>
        ))}
      </dl>
      {moments.length > 0 && (
        <div className="flex flex-wrap gap-1.5 text-[11px]">
          {moments.map((m) => (
            <span key={m.candidate} className={cx('rounded-sm px-1.5 py-0.5 ring-1 ring-inset', m.type === 'action_only' ? 'text-graphite-500 ring-graphite-700' : 'text-bone-200 ring-graphite-600')}
              title={m.evidence}>
              <span className="timecode text-graphite-400">{m.t.toFixed(1)}s</span> {MOMENT_LABEL[m.type]}
            </span>
          ))}
        </div>
      )}
      {d.notes.length > 0 && <p className="text-[11px] text-graphite-400">{d.notes.join(' · ')}</p>}
    </div>
  )
}

export function PlanPanel({ clipId, cfg, plan, stored, busy, planJob, onJob, onToggle }: {
  clipId: string; cfg: EditConfig; plan: EditPlan | null; stored: boolean; busy: boolean; planJob: Job | null; onJob: () => void
  onToggle: (id: string) => void
}) {
  const runAi = async () => {
    try { await api.makePlan(clipId, cfg); toast.info('AI Video Director avviato (LLM locale)'); onJob() } catch (e) { toast.error(e) }
  }
  if (!plan) return <Spinner />
  const items = planItems(plan)
  const global: PlanItem[] = []
  if (plan.music) global.push({ id: 'music', track: 'global', start: 0, end: 0, label: `musica ${MOOD_LABEL[plan.music.mood] ?? plan.music.mood}`, reason: plan.music.reason, color: 'bg-violet-400', value: plan.music.title })
  if (plan.look && (plan.look.grade !== 'none' || plan.look.vignette > 0)) global.push({ id: 'look', track: 'global', start: 0, end: 0, label: `look ${plan.look.grade}`, reason: plan.look.reason, color: 'bg-bone-300', value: `${Math.round(plan.look.intensity * 100)}%` })
  const all = [...global, ...items]
  const off = new Set(cfg.disabled_items)
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={plan.source === 'llm' ? 'violet' : 'zinc'}>{plan.source === 'llm' ? <><Bot size={11} /> AI locale</> : 'regole'}</Badge>
        {stored && <Badge tone="green">salvato</Badge>}
        {busy && <Spinner className="h-3.5 w-3.5" />}
        <button className="btn-cyan ml-auto px-2.5 py-1.5 text-xs" onClick={runAi} disabled={!!planJob || cfg.planner === 'rules'}
          title={cfg.planner === 'rules' ? 'Modalità "solo regole" attiva' : 'Il regista guarda i fotogrammi e ragiona con il modello locale (Ollama), ~1 min'}>
          <Sparkles size={13} /> {planJob ? 'AI in corso…' : 'Rigenera con AI locale'}
        </button>
      </div>

      <DirectorSummary plan={plan} />

      <ol className="max-h-[22rem] divide-y divide-graphite-800 overflow-auto border-y border-graphite-800 text-xs">
        {all.length === 0 && <li className="py-3 text-graphite-400">Nessun intervento: il regista ha scelto di lasciare il video naturale.</li>}
        {all.map((it) => {
          const isOff = off.has(it.id)
          return (
            <li key={it.id} className={cx('grid grid-cols-[2rem_4.6rem_minmax(0,1fr)] items-start gap-2 py-2', isOff && 'opacity-45')}>
              <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[#ff5a1f]" checked={!isOff} onChange={() => onToggle(it.id)}
                aria-label={`${isOff ? 'Attiva' : 'Disattiva'} ${it.label}`} />
              <span className="timecode text-graphite-400">{it.track === 'global' ? 'clip' : it.end - it.start > 0.2 ? `${it.start.toFixed(1)}–${it.end.toFixed(1)}s` : `${it.start.toFixed(1)}s`}</span>
              <span className="min-w-0">
                <span className={cx('flex flex-wrap items-center gap-1.5 font-medium', isOff ? 'text-graphite-400 line-through' : 'text-bone-100')}>
                  <span className={cx('h-2 w-2 shrink-0 rounded-[1px]', it.color)} />{it.label}
                  {it.value && <span className="timecode font-normal text-graphite-400">{it.value}</span>}
                </span>
                <span className="mt-0.5 block text-graphite-400">{it.reason}</span>
              </span>
            </li>
          )
        })}
      </ol>
      <div className="flex flex-wrap items-center gap-3 text-xs">
        {plan.emphasis.length > 0 && <span className="text-graphite-400">Parole evidenziate: <span className="text-bone-300">{plan.emphasis.map((w) => w.word).join(', ')}</span></span>}
        {off.size > 0 && <span className="text-warn">{off.size} disattivati: non verranno applicati al render</span>}
      </div>
      {(plan.notes.length > 0 || plan.issues?.length > 0) && (
        <p className="text-[11px] text-graphite-500">{[...plan.notes.slice(0, 3), ...(plan.issues ?? []).slice(0, 3)].join(' · ')}</p>
      )}
    </div>
  )
}

/** Music choice: Director's track (or yours), mood, level, ducking, preview. */
export function MusicPanel({ cfg, plan, set }: {
  cfg: EditConfig; plan: EditPlan | null; set: <K extends keyof EditConfig>(k: K, v: EditConfig[K]) => void
}) {
  const [tracks, setTracks] = useState<{ id: string; title: string; category: string; origin: string; url: string; license_label: string }[]>([])
  useEffect(() => { api.audioLibrary('music').then((l) => setTracks(l.filter((a) => a.enabled && a.available))).catch(() => setTracks([])) }, [])
  const m = plan?.music
  const chosen = tracks.find((x) => x.id === (cfg.music_track ?? m?.asset_id))
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {(['auto', 'off'] as const).map((v) => (
          <button key={v} className={cx('rounded-sm px-3 py-1.5 text-sm ring-1 ring-inset', cfg.music === v ? 'bg-graphite-800 text-bone-100 ring-tally-500' : 'text-graphite-300 ring-graphite-700 hover:text-bone-100')}
            onClick={() => set('music', v)} aria-pressed={cfg.music === v}>
            {v === 'auto' ? 'Musica scelta dal regista' : 'Solo audio originale'}
          </button>
        ))}
      </div>
      {cfg.music === 'auto' && <>
        {m ? (
          <div className="flex items-start gap-3 border-l-2 border-violet-400 pl-3">
            <Music2 size={18} className="mt-0.5 shrink-0 text-violet-300" />
            <div className="min-w-0 text-sm">
              <p className="text-bone-100">{m.title} <span className="text-graphite-400">· {MOOD_LABEL[m.mood]}{m.bpm ? ` · ${Math.round(m.bpm)} BPM` : ''}</span></p>
              <p className="text-xs text-graphite-400">{m.reason}</p>
              <p className="text-[11px] text-graphite-500">Licenza: {m.license.toUpperCase()}{m.attribution ? ` · ${m.attribution}` : ''} · livello {m.level_db} dB · sotto il parlato {m.duck_db} dB</p>
            </div>
          </div>
        ) : <p className="text-sm text-graphite-400">{plan?.notes.find((n) => /musica|traccia|mood/i.test(n)) ?? 'Nessuna traccia scelta per questa clip.'}</p>}
        {chosen && <audio controls preload="none" src={chosen.url} className="h-8 w-full" />}
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block space-y-1.5 text-sm">
            <span className="eyebrow">Mood</span>
            <select className="input" value={cfg.music_mood} onChange={(e) => set('music_mood', e.target.value as EditConfig['music_mood'])}>
              <option value="auto">Automatico (dal contenuto)</option>
              {Object.entries(MOOD_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="block space-y-1.5 text-sm">
            <span className="eyebrow">Traccia</span>
            <select className="input" value={cfg.music_track ?? ''} onChange={(e) => set('music_track', e.target.value || null)}>
              <option value="">Scelta dal regista</option>
              {tracks.map((x) => <option key={x.id} value={x.id}>{x.title}{x.origin === 'user' ? ' (tua)' : ''}</option>)}
            </select>
          </label>
        </div>
      </>}
    </div>
  )
}
