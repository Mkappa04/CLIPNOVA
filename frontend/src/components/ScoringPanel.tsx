import { RefreshCw, RotateCcw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../services/api'
import { SIGNAL_LABELS } from '../services/format'
import type { ScoringConfig, ScoringWeights } from '../types'
import { Field } from './ui'

const NUMBERS: [keyof ScoringConfig, string, number, number, number][] = [
  ['min_clip_s', 'Durata min (s)', 3, 180, 1],
  ['max_clip_s', 'Durata max (s)', 5, 600, 1],
  ['pre_roll_s', 'Contesto prima (s)', 0, 120, 1],
  ['post_roll_s', 'Contesto dopo (s)', 0, 120, 1],
  ['max_clips', 'Numero max clip', 1, 100, 1],
  ['min_score', 'Score minimo', 0, 100, 1],
  ['min_gap_s', 'Distanza min (s)', 0, 120, 1],
  ['smoothing_s', 'Smussatura (s)', 0.5, 30, 0.5],
]

export function ScoringPanel({ initial, busy, onApply }: {
  initial: Partial<ScoringConfig> | undefined; busy: boolean; onApply: (cfg: ScoringConfig) => void
}) {
  const [defaults, setDefaults] = useState<ScoringConfig | null>(null)
  const [help, setHelp] = useState<Record<string, string>>({})
  const [cfg, setCfg] = useState<ScoringConfig | null>(null)

  useEffect(() => {
    api.scoringDefaults().then((d) => {
      setDefaults(d.config)
      setHelp(d.weights_help)
      setCfg({ ...d.config, ...(initial ?? {}), weights: { ...d.config.weights, ...(initial?.weights ?? {}) } })
    }).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(initial)])

  if (!cfg || !defaults) return null
  const setW = (k: keyof ScoringWeights, v: number) => setCfg({ ...cfg, weights: { ...cfg.weights, [k]: v } })

  return (
    <div className="space-y-5">
      <div>
        <h4 className="label">Pesi dei segnali</h4>
        <div className="space-y-2">
          {(Object.keys(cfg.weights) as (keyof ScoringWeights)[]).map((k) => (
            <label key={k} className="grid grid-cols-[130px_1fr_34px] items-center gap-3 text-sm" title={help[k]}>
              <span className="text-zinc-300">{SIGNAL_LABELS[k] ?? k}</span>
              <input type="range" min={0} max={3} step={0.1} value={cfg.weights[k]} className="accent-nova-500"
                     onChange={(e) => setW(k, Number(e.target.value))} />
              <span className="text-right font-mono text-xs text-zinc-400">{cfg.weights[k].toFixed(1)}</span>
            </label>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {NUMBERS.map(([k, label, min, max, step]) => (
          <Field key={k} label={label}>
            <input type="number" className="input" min={min} max={max} step={step} value={cfg[k] as number}
                   onChange={(e) => setCfg({ ...cfg, [k]: Number(e.target.value) })} />
          </Field>
        ))}
        <Field label="Lingua motivazioni">
          <select className="input" value={cfg.reason_language} onChange={(e) => setCfg({ ...cfg, reason_language: e.target.value as 'it' | 'en' })}>
            <option value="it">Italiano</option><option value="en">English</option>
          </select>
        </Field>
      </div>
      <p className="text-xs text-zinc-500">Il ricalcolo usa i dati già analizzati (nessuna nuova trascrizione): è istantaneo. Le clip già messe in revisione o modificate a mano non vengono toccate.</p>
      <div className="flex gap-2">
        <button className="btn-primary" disabled={busy} onClick={() => onApply(cfg)}><RefreshCw size={15} /> Ricalcola clip</button>
        <button className="btn-ghost" onClick={() => setCfg(defaults)}><RotateCcw size={15} /> Default</button>
      </div>
    </div>
  )
}
