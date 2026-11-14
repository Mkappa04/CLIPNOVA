import { ShieldAlert } from 'lucide-react'
import type { Rights } from '../types'
import { AUTH_LABELS, LICENSE_LABELS } from '../services/format'
import { Field } from './ui'

export function RightsForm({ value, onChange }: { value: Rights; onChange: (r: Rights) => void }) {
  const set = <K extends keyof Rights>(k: K, v: Rights[K]) => onChange({ ...value, [k]: v })
  return (
    <div className="space-y-4">
      {value.license_type === 'credit_only' && (
        <div className="flex gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-200">
          <ShieldAlert size={16} className="shrink-0" />
          Dare credito al creator <b>non</b> equivale a un'autorizzazione: l'esportazione resterà bloccata.
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Proprietario dei diritti">
          <input className="input" value={value.owner} onChange={(e) => set('owner', e.target.value)} placeholder="es. nome creator / te stesso" />
        </Field>
        <Field label="URL fonte">
          <input className="input" value={value.source_url} onChange={(e) => set('source_url', e.target.value)} placeholder="https://…" />
        </Field>
        <Field label="Tipo licenza">
          <select className="input" value={value.license_type} onChange={(e) => set('license_type', e.target.value as Rights['license_type'])}>
            {Object.entries(LICENSE_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        <Field label="Stato autorizzazione">
          <select className="input" value={value.authorization_status} onChange={(e) => set('authorization_status', e.target.value as Rights['authorization_status'])}>
            {Object.entries(AUTH_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        <Field label="Scadenza autorizzazione">
          <input type="date" className="input" value={value.expires_at ?? ''} onChange={(e) => set('expires_at', e.target.value || null)} />
        </Field>
        <Field label="Testo attribuzione">
          <input className="input" value={value.attribution_text} onChange={(e) => set('attribution_text', e.target.value)} placeholder="es. 🎥 Clip di @creator" />
        </Field>
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" className="accent-nova-500" checked={value.commercial_use_allowed} onChange={(e) => set('commercial_use_allowed', e.target.checked)} /> Uso commerciale consentito</label>
        <label className="flex items-center gap-2"><input type="checkbox" className="accent-nova-500" checked={value.attribution_required} onChange={(e) => set('attribution_required', e.target.checked)} /> Attribuzione richiesta</label>
      </div>
      <Field label="Restrizioni">
        <textarea className="input min-h-[60px]" value={value.restrictions} onChange={(e) => set('restrictions', e.target.value)} placeholder="es. niente TikTok, niente monetizzazione, solo clip < 60s" />
      </Field>
      <Field label="Prova del permesso" hint="Riferimento a email, DM, contratto o link alla licenza.">
        <input className="input" value={value.evidence} onChange={(e) => set('evidence', e.target.value)} />
      </Field>
    </div>
  )
}
