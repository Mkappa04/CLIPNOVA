import { FolderPlus, FolderSync, Pause, Play, RotateCcw, ScanLine, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Segmented, Slider, Toggle } from '../components/EditorControls'
import { Badge, EmptyState, Field, PageHeader, Spinner, cx } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { FILE_STATUS, formatBytes, timeAgo } from '../services/format'
import { toast } from '../stores/toastStore'
import type { AutomationSettingsT, WatchFolderT } from '../types'

const RIGHTS_PROFILES = {
  own: { label: 'Contenuto proprio, autorizzato', rights: { license_type: 'own_content', authorization_status: 'authorized', commercial_use_allowed: true, attribution_required: false } },
  unknown: { label: 'Da verificare (export bloccato)', rights: { license_type: 'unknown', authorization_status: 'unknown', commercial_use_allowed: false, attribution_required: true } },
} as const

function emptyForm() {
  return {
    name: '', path: '', game: 'GTA 6', creator_name: '', mode: 'reference' as 'reference' | 'copy', recursive: false,
    extensions: '.mp4 .mkv .mov', profile: 'own' as keyof typeof RIGHTS_PROFILES,
    analyze: true, language: 'auto', render_top_n: 3, min_score: 45, detect_webcam: true, subtitle_preset: 'gaming', quality: 'standard',
  }
}

function FolderForm({ onAdded }: { onAdded: () => void }) {
  const [f, setF] = useState(emptyForm())
  const [busy, setBusy] = useState(false)
  const set = <K extends keyof ReturnType<typeof emptyForm>>(k: K, v: ReturnType<typeof emptyForm>[K]) => setF({ ...f, [k]: v })
  const submit = async () => {
    setBusy(true)
    try {
      await api.addWatchFolder({
        name: f.name, path: f.path, game: f.game, creator_name: f.creator_name, mode: f.mode, recursive: f.recursive,
        extensions: f.extensions.split(/[\s,]+/).filter(Boolean), rights: RIGHTS_PROFILES[f.profile].rights,
        pipeline: { analyze: f.analyze, language: f.language, render_top_n: f.render_top_n, min_score: f.min_score,
          detect_webcam: f.detect_webcam, edit_config: { subtitle_preset: f.subtitle_preset, quality: f.quality } },
      })
      toast.success('Cartella aggiunta: verrà controllata al prossimo giro'); setF(emptyForm()); onAdded()
    } catch (e) { toast.error(e) } finally { setBusy(false) }
  }
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Percorso" hint={<>Linux o Windows: <code>C:\Users\tu\Videos\OBS</code> diventa <code>/mnt/c/Users/tu/Videos/OBS</code></>}>
          <input className="input font-mono text-xs" value={f.path} onChange={(e) => set('path', e.target.value)} placeholder="C:\Users\...\Videos" />
        </Field>
        <Field label="Nome"><input className="input" value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="es. Registrazioni OBS" /></Field>
        <Field label="Gioco"><input className="input" value={f.game} onChange={(e) => set('game', e.target.value)} /></Field>
        <Field label="Creator"><input className="input" value={f.creator_name} onChange={(e) => set('creator_name', e.target.value)} placeholder="il tuo nickname" /></Field>
        <Field label="Diritti predefiniti">
          <select className="input" value={f.profile} onChange={(e) => set('profile', e.target.value as keyof typeof RIGHTS_PROFILES)}>
            {Object.entries(RIGHTS_PROFILES).map(([k, p]) => <option key={k} value={k}>{p.label}</option>)}
          </select>
        </Field>
        <Field label="Estensioni"><input className="input font-mono text-xs" value={f.extensions} onChange={(e) => set('extensions', e.target.value)} /></Field>
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <Segmented value={f.mode} onChange={(v) => set('mode', v)} options={[{ value: 'reference', label: 'Riferimento' }, { value: 'copy', label: 'Copia in Linux' }]} />
        <Toggle label="Includi sottocartelle" checked={f.recursive} onChange={(v) => set('recursive', v)} />
      </div>
      <div className="rounded-lg bg-ink-850 p-3 ring-1 ring-ink-700">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-pulse-300">Pipeline automatica</div>
        <div className="grid gap-2 sm:grid-cols-2">
          <Toggle label="Analisi + trascrizione + clip detection" checked={f.analyze} onChange={(v) => set('analyze', v)} />
          <Toggle label="Rileva webcam" checked={f.detect_webcam} onChange={(v) => set('detect_webcam', v)} />
        </div>
        {f.analyze && <div className="mt-2 space-y-2">
          <Slider label="Render migliori" value={f.render_top_n} min={0} max={10} step={1} onChange={(v) => set('render_top_n', v)} fmt={(v) => `${v} clip`} />
          <Slider label="Score minimo" value={f.min_score} min={0} max={100} step={1} onChange={(v) => set('min_score', v)} />
          <div className="flex flex-wrap gap-3">
            <Segmented value={f.subtitle_preset} onChange={(v) => set('subtitle_preset', v)} options={[{ value: 'clean', label: 'Clean' }, { value: 'gaming', label: 'Gaming' }, { value: 'viral', label: 'Viral' }]} />
            <Segmented value={f.quality} onChange={(v) => set('quality', v)} options={[{ value: 'draft', label: 'Bozza' }, { value: 'standard', label: 'Standard' }, { value: 'high', label: 'Alta' }]} />
          </div>
        </div>}
        <p className="mt-2 text-xs text-zinc-500">Le clip renderizzate arrivano nell'Approval Center: non vengono mai approvate né pubblicate automaticamente.</p>
      </div>
      <button className="btn-primary" disabled={busy || !f.path.trim()} onClick={submit}><FolderPlus size={15} /> Aggiungi cartella</button>
    </div>
  )
}

function FolderCard({ f, onChanged }: { f: WatchFolderT; onChanged: () => void }) {
  const [confirm, setConfirm] = useState(false)
  const toggle = async () => {
    try {
      await api.updateWatchFolder(f.id, { name: f.name, path: f.path, enabled: !f.enabled, recursive: f.recursive, extensions: f.extensions, mode: f.mode,
        game: f.game, creator_name: f.creator_name, source: f.source, rights: f.rights, pipeline: f.pipeline, creator_id: f.creator_id })
      onChanged()
    } catch (e) { toast.error(e) }
  }
  const del = async () => { try { await api.deleteWatchFolder(f.id); toast.success('Cartella non più monitorata (file e video restano)'); onChanged() } catch (e) { toast.error(e) } }
  return (
    <li className={cx('card p-3', !f.enabled && 'opacity-60')}>
      <div className="flex flex-wrap items-center gap-2">
        <FolderSync size={16} className="text-nova-400" />
        <span className="font-medium text-white">{f.name || 'Cartella'}</span>
        {f.on_windows && <Badge tone="cyan">Windows</Badge>}
        {f.creator && <Badge tone="violet">creator: {f.creator}</Badge>}
        {!f.exists && <Badge tone="red">non trovata</Badge>}
        <Badge>{f.mode === 'copy' ? 'copia' : 'riferimento'}</Badge>
        <span className="ml-auto flex gap-1.5">
          <button className="btn-ghost px-2 py-1 text-xs" onClick={toggle}>{f.enabled ? 'Disattiva' : 'Attiva'}</button>
          {!confirm ? <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setConfirm(true)} aria-label="Rimuovi cartella"><Trash2 size={12} /></button>
            : <button className="btn-danger px-2 py-1 text-xs" onClick={del}>Conferma</button>}
        </span>
      </div>
      <div className="mt-1 break-all font-mono text-xs text-zinc-500">{f.path}</div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-400">
        <span>{f.game}</span>
        <span>{f.pipeline.analyze ? `analisi → render top ${f.pipeline.render_top_n} (score ≥ ${f.pipeline.min_score})` : 'solo import'}</span>
        {Object.entries(f.counts).map(([k, v]) => <span key={k}>{FILE_STATUS[k]?.label ?? k}: {v}</span>)}
        {f.last_scan_at && <span>scansione {timeAgo(f.last_scan_at)}</span>}
      </div>
      {f.last_error && <p className="mt-1 text-xs text-red-300">{f.last_error}</p>}
    </li>
  )
}

export function AutoImport() {
  const { data: status, reload: reloadStatus } = useApi(() => api.automationStatus(), [], 3000)
  const { data: folders, reload: reloadFolders } = useApi(() => api.watchFolders(), [], 5000)
  const { data: files, reload: reloadFiles } = useApi(() => api.watchedFiles({ limit: 100 }), [], 3000)
  const [sched, setSched] = useState<AutomationSettingsT | null>(null)
  const [showForm, setShowForm] = useState(false)
  useEffect(() => { if (status && !sched) setSched(status.settings) }, [status])

  const save = async (s: AutomationSettingsT) => {
    try { await api.saveAutomation(s); setSched(s); reloadStatus() } catch (e) { toast.error(e) }
  }
  const scan = async () => {
    try { const r = await api.scanNow(); toast.info(r.paused ? 'In pausa' : `Scansione: ${r.seen} file visti, ${r.imported} importati`); reloadFiles(); reloadFolders(); reloadStatus() }
    catch (e) { toast.error(e) }
  }
  const retry = async (id: string) => { try { await api.retryWatchedFile(id); reloadFiles() } catch (e) { toast.error(e) } }
  const folderName = (id: string) => folders?.find((f) => f.id === id)?.name || 'cartella'

  return (
    <>
      <PageHeader title="Auto Import" subtitle="Cartelle monitorate (OBS, ShadowPlay…) → import → analisi → render delle migliori clip → revisione"
        actions={status && sched && <>
          <button className="btn-ghost" onClick={scan}><ScanLine size={15} /> Scansiona ora</button>
          {sched.paused ? <button className="btn-primary" onClick={() => save({ ...sched, paused: false })}><Play size={15} /> Riprendi</button>
            : <button className="btn-ghost" onClick={() => save({ ...sched, paused: true })}><Pause size={15} /> Pausa</button>}
        </>} />
      {!status && <Spinner />}
      {status && sched && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div className="card p-4 text-sm">
              <div className="text-xs uppercase tracking-wider text-zinc-500">Watcher</div>
              <div className="mt-1 font-semibold text-white">
                {sched.paused ? 'In pausa' : status.watcher_running ? `Attivo · ogni ${status.poll_s}s` : status.watcher_enabled ? 'Avvio…' : 'Disattivato (CLIPNOVA_AUTOMATION_ENABLED)'}
              </div>
              <div className="text-xs text-zinc-500">{status.last_tick_at ? `ultimo controllo ${timeAgo(status.last_tick_at)}` : 'nessun controllo ancora'} · file stabile dopo {status.stable_s}s · attesa remux .mkv {status.remux_grace_s}s</div>
            </div>
            <div className={cx('card p-4 text-sm', !status.can_run_now && 'border-amber-500/40')}>
              <div className="text-xs uppercase tracking-wider text-zinc-500">Lavori pesanti</div>
              <div className={cx('mt-1 font-semibold', status.can_run_now ? 'text-emerald-300' : 'text-amber-300')}>{status.can_run_now ? 'Consentiti ora' : 'Rimandati'}</div>
              <div className="text-xs text-zinc-500">{status.blocked_reason || 'Un job pesante alla volta (Whisper, NVENC, Ollama non si sovrappongono)'}</div>
            </div>
            <div className="card p-4 text-sm">
              <div className="text-xs uppercase tracking-wider text-zinc-500">File</div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {Object.entries(status.counts).map(([k, v]) => <Badge key={k} tone={FILE_STATUS[k]?.tone ?? 'zinc'}>{FILE_STATUS[k]?.label ?? k} {v}</Badge>)}
                {!Object.keys(status.counts).length && <span className="text-zinc-500">nessuno</span>}
              </div>
            </div>
          </div>

          <section className="card space-y-3 p-4">
            <h2 className="font-display font-semibold text-white">Quando lavorare</h2>
            <div className="flex flex-wrap items-center gap-4">
              <Toggle label="Solo in una fascia oraria" checked={sched.window.enabled} onChange={(v) => save({ ...sched, window: { ...sched.window, enabled: v } })} />
              {sched.window.enabled && <>
                <input type="time" className="input w-auto" value={sched.window.start} onChange={(e) => setSched({ ...sched, window: { ...sched.window, start: e.target.value } })} onBlur={() => save(sched)} />
                <span className="text-zinc-500">→</span>
                <input type="time" className="input w-auto" value={sched.window.end} onChange={(e) => setSched({ ...sched, window: { ...sched.window, end: e.target.value } })} onBlur={() => save(sched)} />
              </>}
              <Toggle label="Solo quando il PC è inattivo" checked={sched.idle_only} onChange={(v) => save({ ...sched, idle_only: v })}
                hint="Stima: carico CPU e uso GPU (se stai giocando la GPU è occupata)" />
            </div>
          </section>

          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-display text-lg font-semibold text-white">Cartelle monitorate</h2>
              <button className="btn-cyan" onClick={() => setShowForm(!showForm)}><FolderPlus size={15} /> {showForm ? 'Chiudi' : 'Aggiungi'}</button>
            </div>
            {showForm && <div className="card mb-3 p-4"><FolderForm onAdded={() => { setShowForm(false); reloadFolders() }} /></div>}
            {folders && folders.length === 0 && !showForm && (
              <EmptyState icon={<FolderSync size={26} />} title="Nessuna cartella monitorata"
                text="Aggiungi la cartella dove OBS o ShadowPlay salvano le registrazioni: i nuovi video verranno importati e lavorati da soli." />
            )}
            <ul className="space-y-2">{folders?.map((f) => <FolderCard key={f.id} f={f} onChanged={reloadFolders} />)}</ul>
          </section>

          <section>
            <h2 className="mb-3 font-display text-lg font-semibold text-white">File rilevati</h2>
            {files && files.length === 0 && <p className="text-sm text-zinc-500">Nessun file ancora.</p>}
            <ul className="divide-y divide-ink-700 rounded-xl bg-ink-900/80 ring-1 ring-ink-700">
              {files?.map((f) => (
                <li key={f.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
                  <Badge tone={FILE_STATUS[f.status]?.tone ?? 'zinc'}>{FILE_STATUS[f.status]?.label ?? f.status}</Badge>
                  <span className="min-w-0 flex-1 truncate text-zinc-100" title={f.path}>{f.name}</span>
                  <span className="text-xs text-zinc-500">{folderName(f.folder_id)} · {formatBytes(f.size)}{f.stage ? ` · ${f.stage}` : ''}</span>
                  <span className="w-full text-xs text-zinc-400 sm:w-auto">{f.reason}</span>
                  {f.status === 'done' && <Link className="text-xs text-pulse-400 hover:underline" to="/approval">Revisiona →</Link>}
                  {['error', 'skipped'].includes(f.status) && <button className="btn-ghost px-2 py-1 text-xs" onClick={() => retry(f.id)}><RotateCcw size={12} /> Riprova</button>}
                  <span className="text-[11px] text-zinc-600">{timeAgo(f.updated_at)}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </>
  )
}
