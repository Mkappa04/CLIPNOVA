import { CalendarClock, ExternalLink, KeyRound, Lock, Plus, RotateCcw, Send, Trash2, XCircle } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, EmptyState, Field, PageHeader, StatusBadge, cx } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { PLATFORM_LABELS, formatDate } from '../services/format'
import { toast } from '../stores/toastStore'
import type { ExportItem, Platform, PublishingStatus, SocialAccount } from '../types'
import { ExportFiles } from './ApprovalCenter'

function ExportRow({ e, onDeleted }: { e: ExportItem; onDeleted: () => void }) {
  const [open, setOpen] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const del = async () => { try { await api.deleteExport(e.id); toast.success('Export eliminato'); onDeleted() } catch (err) { toast.error(err) } }
  return (
    <li className="card p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-zinc-100">{e.clip_title || e.video_title}</span>
        {e.platforms.map((p) => <Badge key={p} tone="violet">{PLATFORM_LABELS[p]}</Badge>)}
        <Badge tone={e.purpose === 'commercial' ? 'cyan' : 'zinc'}>{e.purpose === 'commercial' ? 'commerciale' : 'non commerciale'}</Badge>
        <span className="text-xs text-zinc-500">{formatDate(e.created_at)}</span>
        <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setOpen(!open)}>{open ? 'Chiudi' : 'File'}</button>
        {!confirm ? <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setConfirm(true)} aria-label="Elimina export"><Trash2 size={13} /></button>
          : <button className="btn-danger px-2 py-1 text-xs" onClick={del}>Conferma</button>}
      </div>
      {open && <div className="mt-2"><ExportFiles e={e} /></div>}
    </li>
  )
}

function AccountForm({ status, onAdded }: { status: PublishingStatus; onAdded: () => void }) {
  const [platform, setPlatform] = useState<Platform>('youtube')
  const [name, setName] = useState('')
  const [creds, setCreds] = useState<Record<string, string>>({})
  const provider = status.providers.find((p) => p.platform === platform)
  const add = async () => {
    try { await api.addAccount(platform, name, creds); setCreds({}); setName(''); toast.success('Account salvato (credenziali cifrate)'); onAdded() }
    catch (e) { toast.error(e) }
  }
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Piattaforma">
          <select className="input" value={platform} onChange={(e) => { setPlatform(e.target.value as Platform); setCreds({}) }}>
            {status.providers.map((p) => <option key={p.platform} value={p.platform}>{p.name}</option>)}
          </select>
        </Field>
        <Field label="Nome account"><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="es. Canale principale" /></Field>
        {provider?.credential_fields.map((f) => (
          <Field key={f} label={f}>
            <input className="input font-mono text-xs" type={f.includes('url') || f.includes('id') ? 'text' : 'password'} autoComplete="off"
                   value={creds[f] ?? ''} onChange={(e) => setCreds({ ...creds, [f]: e.target.value })} />
          </Field>
        ))}
      </div>
      {provider && <p className="text-xs text-zinc-400">{provider.notes} <a className="text-pulse-400 hover:underline" href={provider.docs_url} target="_blank" rel="noreferrer">Documentazione ufficiale <ExternalLink size={11} className="inline" /></a></p>}
      <button className="btn-cyan" onClick={add}><Plus size={15} /> Salva account</button>
    </div>
  )
}

function ScheduleForm({ exports, accounts, enabled, onDone }: { exports: ExportItem[]; accounts: SocialAccount[]; enabled: boolean; onDone: () => void }) {
  const [exportId, setExportId] = useState('')
  const [accountId, setAccountId] = useState('')
  const [when, setWhen] = useState('')
  const [privacy, setPrivacy] = useState<'private' | 'unlisted' | 'public'>('private')
  const [confirm, setConfirm] = useState(false)
  const exp = exports.find((e) => e.id === exportId)
  const usable = useMemo(() => accounts.filter((a) => exp?.platforms.includes(a.platform)), [accounts, exp])
  const submit = async () => {
    try {
      await api.schedulePublication({ export_id: exportId, account_id: accountId, privacy, confirm,
        scheduled_at: when ? new Date(when).toISOString() : undefined })
      toast.success(when ? 'Pubblicazione programmata' : 'Pubblicazione in coda'); setConfirm(false); onDone()
    } catch (e) { toast.error(e) }
  }
  return (
    <div className={cx('space-y-3', !enabled && 'pointer-events-none opacity-50')}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Export (clip approvata)">
          <select className="input" value={exportId} onChange={(e) => { setExportId(e.target.value); setAccountId('') }}>
            <option value="">—</option>
            {exports.map((e) => <option key={e.id} value={e.id}>{(e.clip_title || e.video_title).slice(0, 60)} · {formatDate(e.created_at)}</option>)}
          </select>
        </Field>
        <Field label="Account">
          <select className="input" value={accountId} onChange={(e) => setAccountId(e.target.value)} disabled={!exp}>
            <option value="">—</option>
            {usable.map((a) => <option key={a.id} value={a.id}>{PLATFORM_LABELS[a.platform]} · {a.display_name}</option>)}
          </select>
        </Field>
        <Field label="Quando" hint="Vuoto = appena possibile"><input type="datetime-local" className="input" value={when} onChange={(e) => setWhen(e.target.value)} /></Field>
        <Field label="Visibilità">
          <select className="input" value={privacy} onChange={(e) => setPrivacy(e.target.value as typeof privacy)}>
            <option value="private">Privato</option><option value="unlisted">Non in elenco / amici</option><option value="public">Pubblico</option>
          </select>
        </Field>
      </div>
      <label className="flex items-start gap-2 text-sm text-zinc-200">
        <input type="checkbox" className="mt-0.5 accent-nova-500" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
        Confermo di voler pubblicare questa clip approvata con il testo e i diritti verificati nell'export.
      </label>
      <button className="btn-primary" disabled={!exportId || !accountId || !confirm} onClick={submit}><Send size={15} /> Programma pubblicazione</button>
    </div>
  )
}

export function PublishedContent() {
  const { data: status } = useApi(() => api.publishingStatus())
  const { data: exports, reload: reloadExports } = useApi(() => api.exports({ limit: 100 }), [], 10000)
  const { data: pubs, reload: reloadPubs } = useApi(() => api.publications(), [], 5000)
  const { data: accounts, reload: reloadAccounts } = useApi(() => api.accounts())
  const [openLog, setOpenLog] = useState<string | null>(null)
  const [confirmAcc, setConfirmAcc] = useState<string | null>(null)

  const pubAction = async (id: string, a: 'cancel' | 'retry') => {
    try { await (a === 'cancel' ? api.cancelPublication(id) : api.retryPublication(id)); reloadPubs() } catch (e) { toast.error(e) }
  }
  const delAccount = async (id: string) => {
    try { await api.deleteAccount(id); setConfirmAcc(null); reloadAccounts(); toast.success('Account rimosso') } catch (e) { toast.error(e) }
  }

  return (
    <>
      <PageHeader title="Published Content" subtitle="Pacchetti di export, pubblicazioni e account social" />
      {status && (
        <div className={cx('card mb-6 flex items-start gap-3 p-4 text-sm', status.enabled ? 'border-amber-500/40' : 'border-ink-600')}>
          <Lock size={18} className={status.enabled ? 'text-amber-400' : 'text-zinc-400'} />
          <div>
            <div className="font-semibold text-white">Pubblicazione automatica {status.enabled ? 'ABILITATA' : 'disabilitata'}</div>
            <p className="text-zinc-400">{status.explanation}</p>
            {status.export_copy_dir && <p className="mt-1 text-xs text-zinc-500">Copia automatica degli export in <span className="font-mono">{status.export_copy_dir}</span></p>}
          </div>
        </div>
      )}

      <section className="mb-8">
        <h2 className="mb-3 font-display text-lg font-semibold text-white">Export ({exports?.length ?? 0})</h2>
        {exports && exports.length === 0 && (
          <EmptyState icon={<Send size={26} />} title="Nessun export" text="Approva una clip nell'Approval Center e crea il pacchetto da caricare."
            action={<Link to="/approval" className="btn-primary">Apri l'Approval Center</Link>} />
        )}
        <ul className="space-y-2">{exports?.map((e) => <ExportRow key={e.id} e={e} onDeleted={reloadExports} />)}</ul>
      </section>

      <section className="mb-8">
        <h2 className="mb-3 font-display text-lg font-semibold text-white">Pubblicazioni</h2>
        {pubs && pubs.length === 0 && <p className="text-sm text-zinc-500">Nessuna pubblicazione programmata.</p>}
        <ul className="space-y-2">
          {pubs?.map((p) => (
            <li key={p.id} className="card p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={p.status} />
                <Badge tone="violet">{PLATFORM_LABELS[p.platform]}</Badge>
                <span className="min-w-0 flex-1 truncate text-zinc-100">{p.clip_title}</span>
                <span className="text-xs text-zinc-500"><CalendarClock size={12} className="mr-1 inline" />{formatDate(p.scheduled_at)} · tentativi {p.attempts}/{p.max_attempts}</span>
                {p.remote_url && <a className="btn-ghost px-2 py-1 text-xs" href={p.remote_url} target="_blank" rel="noreferrer"><ExternalLink size={12} /> Apri</a>}
                {p.status === 'scheduled' && <button className="btn-ghost px-2 py-1 text-xs" onClick={() => pubAction(p.id, 'cancel')}><XCircle size={12} /> Annulla</button>}
                {p.status === 'failed' && <button className="btn-ghost px-2 py-1 text-xs" onClick={() => pubAction(p.id, 'retry')}><RotateCcw size={12} /> Riprova</button>}
                <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setOpenLog(openLog === p.id ? null : p.id)}>Log</button>
              </div>
              {p.last_error && <p className="mt-1 text-xs text-red-300">{p.last_error}</p>}
              {openLog === p.id && (
                <ul className="mt-2 max-h-40 overflow-y-auto rounded bg-ink-850 p-2 font-mono text-[11px] text-zinc-400">
                  {p.log.map((l, i) => <li key={i}>{formatDate(l.at)} · {l.msg}</li>)}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </section>

      {status && (
        <div className="grid gap-5 lg:grid-cols-2">
          <section className="card p-4">
            <h2 className="mb-3 flex items-center gap-2 font-display font-semibold text-white"><KeyRound size={16} className="text-nova-400" /> Account (API ufficiali)</h2>
            <ul className="mb-4 space-y-2">
              {accounts?.map((a) => (
                <li key={a.id} className="flex flex-wrap items-center gap-2 rounded-lg bg-ink-850 p-2 text-sm ring-1 ring-ink-700">
                  <Badge tone="violet">{PLATFORM_LABELS[a.platform]}</Badge>
                  <span className="flex-1 text-zinc-100">{a.display_name}</span>
                  <StatusBadge status={a.status === 'connected' ? 'ready' : 'error'} />
                  {confirmAcc === a.id ? <button className="btn-danger px-2 py-1 text-xs" onClick={() => delAccount(a.id)}>Conferma</button>
                    : <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setConfirmAcc(a.id)} aria-label="Rimuovi account"><Trash2 size={12} /></button>}
                </li>
              ))}
              {accounts?.length === 0 && <li className="text-sm text-zinc-500">Nessun account collegato.</li>}
            </ul>
            <AccountForm status={status} onAdded={reloadAccounts} />
          </section>
          <section className="card p-4">
            <h2 className="mb-3 flex items-center gap-2 font-display font-semibold text-white"><Send size={16} className="text-nova-400" /> Programma una pubblicazione</h2>
            {!status.enabled && <p className="mb-3 text-xs text-amber-300">Disabilitato: imposta CLIPNOVA_PUBLISHING_ENABLED=true nel file .env e riavvia.</p>}
            <ScheduleForm exports={exports ?? []} accounts={accounts ?? []} enabled={status.enabled} onDone={reloadPubs} />
          </section>
        </div>
      )}
    </>
  )
}
