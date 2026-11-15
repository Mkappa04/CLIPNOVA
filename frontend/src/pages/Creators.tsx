import { Copy, FileCheck2, FolderPlus, MessageSquareText, Plus, Trash2, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Toggle } from '../components/EditorControls'
import { Badge, EmptyState, Field, PageHeader, cx } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { formatDate } from '../services/format'
import { toast } from '../stores/toastStore'
import type { CreatorT } from '../types'

const STATUSES = [
  ['to_contact', 'da contattare', 'zinc'], ['contacted', 'contattato', 'cyan'], ['waiting', 'in attesa', 'amber'],
  ['authorized', 'autorizzato', 'green'], ['refused', 'rifiutato', 'red'], ['expired', 'scaduto', 'red'],
] as const

function MessagePanel({ c }: { c: CreatorT }) {
  const [f, setF] = useState({ language: c.language === 'en' ? 'en' : 'it', sender: '', channel: '', what: '', commercial: false,
    attribution: '', platforms: ['tiktok', 'instagram', 'youtube'], use_llm: false })
  const [out, setOut] = useState<{ text: string; warnings: string[]; generated_by: string } | null>(null)
  const gen = async () => { try { setOut(await api.permissionMessage(c.id, f)) } catch (e) { toast.error(e) } }
  const copy = async () => { if (out) { await navigator.clipboard.writeText(out.text); toast.success('Copiato: invialo tu dal canale che preferisci') } }
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2">
        <Field label="Il tuo nome"><input className="input" value={f.sender} onChange={(e) => setF({ ...f, sender: e.target.value })} /></Field>
        <Field label="Il tuo canale"><input className="input" value={f.channel} onChange={(e) => setF({ ...f, channel: e.target.value })} placeholder="@tuocanale" /></Field>
        <Field label="Cosa vorresti usare"><input className="input" value={f.what} onChange={(e) => setF({ ...f, what: e.target.value })} placeholder="es. momenti delle tue live su GTA 6" /></Field>
        <Field label="Attribuzione offerta"><input className="input" value={f.attribution} onChange={(e) => setF({ ...f, attribution: e.target.value })} placeholder={`es. @${c.name.replace(/\s/g, '')} in ogni descrizione`} /></Field>
      </div>
      <div className="flex flex-wrap gap-4">
        <select className="input w-auto py-1 text-xs" value={f.language} onChange={(e) => setF({ ...f, language: e.target.value })}><option value="it">Italiano</option><option value="en">English</option></select>
        <Toggle label="Uso commerciale" checked={f.commercial} onChange={(v) => setF({ ...f, commercial: v })} />
        <Toggle label="Rifinisci con LLM locale" checked={f.use_llm} onChange={(v) => setF({ ...f, use_llm: v })} />
      </div>
      <button className="btn-cyan" onClick={gen}><MessageSquareText size={14} /> Genera messaggio</button>
      {out && <>
        {out.warnings.map((w) => <p key={w} className="text-xs text-amber-300">⚠ {w}</p>)}
        <textarea className="input min-h-[220px] font-mono text-xs" value={out.text} onChange={(e) => setOut({ ...out, text: e.target.value })} />
        <div className="flex items-center gap-2"><button className="btn-primary" onClick={copy}><Copy size={14} /> Copia</button>
          <span className="text-xs text-zinc-500">{out.generated_by} · CLIPNOVA non invia messaggi: l'invio resta manuale.</span></div>
      </>}
    </div>
  )
}

function PermissionForm({ c, onSaved }: { c: CreatorT; onSaved: (c: CreatorT) => void }) {
  const today = new Date().toISOString().slice(0, 10)
  const [f, setF] = useState({ granted_at: today, expires_at: '', scope: '', commercial_use: false, attribution_text: '', restrictions: '', evidence_text: '' })
  const [file, setFile] = useState<File | null>(null)
  const save = async () => {
    const form = new FormData()
    Object.entries(f).forEach(([k, v]) => { if (v !== '') form.append(k, String(v)) })
    if (file) form.append('evidence', file)
    try { onSaved(await api.addPermission(c.id, form)); toast.success('Consenso registrato: creator autorizzato') } catch (e) { toast.error(e) }
  }
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2">
        <Field label="Data del consenso"><input type="date" className="input" value={f.granted_at} onChange={(e) => setF({ ...f, granted_at: e.target.value })} /></Field>
        <Field label="Scadenza (facoltativa)"><input type="date" className="input" value={f.expires_at} onChange={(e) => setF({ ...f, expires_at: e.target.value })} /></Field>
        <Field label="Ambito"><input className="input" value={f.scope} onChange={(e) => setF({ ...f, scope: e.target.value })} placeholder="es. clip dalle live GTA 6" /></Field>
        <Field label="Attribuzione concordata *"><input className="input" value={f.attribution_text} onChange={(e) => setF({ ...f, attribution_text: e.target.value })} /></Field>
        <Field label="Restrizioni"><input className="input" value={f.restrictions} onChange={(e) => setF({ ...f, restrictions: e.target.value })} /></Field>
        <Field label="File di prova (screenshot, PDF, email)"><input type="file" className="input py-1 text-xs" accept=".png,.jpg,.jpeg,.webp,.pdf,.txt,.eml,.msg" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
      </div>
      <Field label="Testo del consenso (copia della risposta)"><textarea className="input min-h-[60px]" value={f.evidence_text} onChange={(e) => setF({ ...f, evidence_text: e.target.value })} /></Field>
      <Toggle label="Uso commerciale consentito" checked={f.commercial_use} onChange={(v) => setF({ ...f, commercial_use: v })} />
      <button className="btn-primary" onClick={save} disabled={!f.attribution_text.trim() || (!f.evidence_text.trim() && !file)}><FileCheck2 size={14} /> Registra consenso</button>
    </div>
  )
}

function CreatorCard({ c, onChanged }: { c: CreatorT; onChanged: () => void }) {
  const [tab, setTab] = useState<'' | 'msg' | 'perm' | 'folder'>('')
  const [cur, setCur] = useState(c)
  const [note, setNote] = useState('')
  const [folderPath, setFolderPath] = useState('')
  const [confirm, setConfirm] = useState(false)
  useEffect(() => setCur(c), [c])
  const setStatus = async (status: string) => { try { setCur(await api.updateCreator(c.id, { status, note })); setNote(''); onChanged() } catch (e) { toast.error(e) } }
  const revoke = async (pid: string) => { try { setCur(await api.revokePermission(c.id, pid)); onChanged() } catch (e) { toast.error(e) } }
  const folder = async () => { try { setCur(await api.creatorFolder(c.id, folderPath)); toast.success('Cartella dedicata creata e monitorata'); onChanged() } catch (e) { toast.error(e) } }
  const del = async () => { try { await api.deleteCreator(c.id); onChanged() } catch (e) { toast.error(e) } }
  const st = STATUSES.find((s) => s[0] === cur.status)
  const valid = cur.permissions.find((p) => p.valid)
  return (
    <li className="card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-display text-lg font-semibold text-white">{cur.name}</span>
        <Badge tone={st?.[2] ?? 'zinc'}>{st?.[1] ?? cur.status}</Badge>
        {cur.language && <Badge>{cur.language}</Badge>}
        {cur.channels.map((ch, i) => ch.url && <a key={i} href={ch.url} target="_blank" rel="noreferrer" className="text-xs text-pulse-400 hover:underline">{ch.platform}</a>)}
        {valid?.days_left != null && valid.days_left <= 7 && <Badge tone="amber">scade tra {valid.days_left} g</Badge>}
        <span className="ml-auto">{!confirm ? <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setConfirm(true)} aria-label="Elimina creator"><Trash2 size={12} /></button>
          : <button className="btn-danger px-2 py-1 text-xs" onClick={del}>Conferma</button>}</span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input className="input w-56 py-1 text-xs" placeholder="nota per il cambio di stato" value={note} onChange={(e) => setNote(e.target.value)} />
        {STATUSES.filter((s) => s[0] !== cur.status && s[0] !== 'expired').map(([k, l]) =>
          <button key={k} className="btn-ghost px-2 py-1 text-xs" onClick={() => setStatus(k)}>→ {l}</button>)}
      </div>
      {cur.permissions.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs">
          {cur.permissions.map((p) => (
            <li key={p.id} className={cx('flex flex-wrap items-center gap-2 rounded bg-ink-850 px-2 py-1.5', !p.valid && 'opacity-60')}>
              <Badge tone={p.valid ? 'green' : 'red'}>{p.revoked ? 'revocato' : p.valid ? 'valido' : 'scaduto'}</Badge>
              <span className="text-zinc-300">{p.granted_at}{p.expires_at ? ` → ${p.expires_at}` : ' · senza scadenza'}</span>
              <span className="text-zinc-400">{p.scope}</span>
              <span className="text-zinc-400">{p.commercial_use ? 'commerciale' : 'non commerciale'} · {p.attribution_text}</span>
              {p.has_evidence_file && <a className="text-pulse-400 hover:underline" href={api.evidenceUrl(cur.id, p.id)} target="_blank" rel="noreferrer">prova</a>}
              {p.valid && <button className="ml-auto text-red-300 hover:underline" onClick={() => revoke(p.id)}>revoca</button>}
            </li>
          ))}
        </ul>
      )}
      {cur.watch_folders.length > 0 && <p className="mt-2 text-xs text-zinc-400">Cartella dedicata: <span className="font-mono">{cur.watch_folders.map((f) => f.path).join(', ')}</span></p>}
      <div className="mt-3 flex flex-wrap gap-2 border-t border-ink-700 pt-3">
        <button className={cx('btn-ghost px-2.5 py-1 text-xs', tab === 'msg' && 'ring-nova-500')} onClick={() => setTab(tab === 'msg' ? '' : 'msg')}><MessageSquareText size={13} /> Richiesta permesso</button>
        <button className={cx('btn-ghost px-2.5 py-1 text-xs', tab === 'perm' && 'ring-nova-500')} onClick={() => setTab(tab === 'perm' ? '' : 'perm')}><FileCheck2 size={13} /> Registra consenso</button>
        {valid && <button className={cx('btn-ghost px-2.5 py-1 text-xs', tab === 'folder' && 'ring-nova-500')} onClick={() => setTab(tab === 'folder' ? '' : 'folder')}><FolderPlus size={13} /> Cartella dedicata</button>}
      </div>
      {tab === 'msg' && <div className="mt-3"><MessagePanel c={cur} /></div>}
      {tab === 'perm' && <div className="mt-3"><PermissionForm c={cur} onSaved={(x) => { setCur(x); setTab(''); onChanged() }} /></div>}
      {tab === 'folder' && (
        <div className="mt-3 space-y-2">
          <Field label="Percorso (vuoto = data/inbox/<creator>)" hint="Può essere una cartella condivisa, anche Windows (C:\...). I file depositati qui vengono importati con i diritti del consenso.">
            <input className="input font-mono text-xs" value={folderPath} onChange={(e) => setFolderPath(e.target.value)} />
          </Field>
          <button className="btn-cyan" onClick={folder}><FolderPlus size={14} /> Crea e monitora</button>
        </div>
      )}
      {cur.status_history.length > 1 && (
        <details className="mt-2 text-xs text-zinc-500"><summary className="cursor-pointer">Storico</summary>
          <ul className="mt-1 space-y-0.5">{cur.status_history.map((h, i) => <li key={i}>{h.at ? formatDate(h.at) : '—'} · {h.from ?? '∅'} → {h.to}{h.note ? ` · ${h.note}` : ''}</li>)}</ul>
        </details>
      )}
    </li>
  )
}

export function Creators() {
  const { data: creators, reload } = useApi(() => api.creators(), [], 15000)
  const [filter, setFilter] = useState('')
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const add = async () => {
    try { await api.addCreator({ name, channels: url ? [{ platform: url.includes('twitch') ? 'twitch' : url.includes('youtu') ? 'youtube' : 'other', url }] : [] }); setName(''); setUrl(''); reload() }
    catch (e) { toast.error(e) }
  }
  const list = (creators ?? []).filter((c) => !filter || c.status === filter)
  return (
    <>
      <PageHeader title="Creators" subtitle="Permessi dei creator: richiesta, consenso documentato, cartella dedicata con diritti precompilati" />
      <div className="card mb-5 flex flex-wrap items-end gap-3 p-4">
        <Field label="Nome"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Link canale"><input className="input w-72" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.twitch.tv/..." /></Field>
        <button className="btn-cyan" disabled={!name.trim()} onClick={add}><Plus size={15} /> Aggiungi creator</button>
      </div>
      <div className="mb-4 flex flex-wrap gap-2">
        <button className={cx('rounded-full px-3 py-1 text-sm ring-1', !filter ? 'bg-nova-600 text-white ring-nova-500' : 'text-zinc-400 ring-ink-600')} onClick={() => setFilter('')}>Tutti</button>
        {STATUSES.map(([k, l]) => (
          <button key={k} className={cx('rounded-full px-3 py-1 text-sm ring-1', filter === k ? 'bg-nova-600 text-white ring-nova-500' : 'text-zinc-400 ring-ink-600')} onClick={() => setFilter(k)}>
            {l} {(creators ?? []).filter((c) => c.status === k).length}
          </button>
        ))}
      </div>
      {creators && list.length === 0 && <EmptyState icon={<Users size={26} />} title="Nessun creator" text="Aggiungili a mano o dalla pagina Discovery." />}
      <ul className="space-y-3">{list.map((c) => <CreatorCard key={c.id} c={c} onChanged={reload} />)}</ul>
    </>
  )
}
