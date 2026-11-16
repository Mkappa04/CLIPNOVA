import { ImageUp, Save, Stamp, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Section, Segmented, Slider, Toggle } from '../components/EditorControls'
import { PageHeader, Spinner } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { formatBytes } from '../services/format'
import { toast } from '../stores/toastStore'
import type { BrandKit as BrandKitT, BrandSettings } from '../types'

const CORNERS: { value: BrandSettings['position']; label: string }[] = [
  { value: 'top-left', label: '↖ Alto sinistra' }, { value: 'top-right', label: '↗ Alto destra' },
  { value: 'bottom-left', label: '↙ Basso sinistra' }, { value: 'bottom-right', label: '↘ Basso destra' },
]

/** Where the logo will be on a 1080x1920 frame, computed like the renderer does (safe area included). */
function place(kit: BrandKitT, s: BrandSettings) {
  if (!kit.logo) return null
  const W = 1080, H = 1920
  let w = Math.floor((W * s.size) / 2) * 2
  let h = Math.floor(Math.round((w * kit.logo.height) / kit.logo.width) / 2) * 2
  const maxH = Math.floor(H * 0.16 / 2) * 2
  if (h > maxH) { h = maxH; w = Math.floor(Math.round((h * kit.logo.width) / kit.logo.height) / 2) * 2 }
  const side = s.safe_area ? 36 : 0, top = s.safe_area ? 190 : 0, bottom = s.safe_area ? 380 : 0
  const extra = s.safe_area && s.position === 'bottom-right' ? 150 : 0
  const x = s.position.includes('left') ? s.margin + side : W - w - s.margin - side - extra
  const y = s.position.startsWith('top') ? s.margin + top : H - h - s.margin - bottom
  return { x: Math.max(0, Math.min(W - w, x)) / W, y: Math.max(0, Math.min(H - h, y)) / H, w: w / W, h: h / H }
}

export function BrandKit() {
  const { data: kit, reload, setData } = useApi(() => api.brandKit())
  const [s, setS] = useState<BrandSettings | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => { if (kit && !s) setS(kit.settings) }, [kit]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!kit || !s) return <><PageHeader title="Brand Kit" /><Spinner /></>
  const dirty = JSON.stringify(s) !== JSON.stringify(kit.settings)
  const box = place(kit, s)

  const upload = async (f: File | undefined) => {
    if (!f) return
    if (f.size > kit.limits.max_mb * 1024 * 1024) { toast.error(`File troppo grande (massimo ${kit.limits.max_mb} MB)`); return }
    setBusy(true)
    try {
      const r = await api.uploadLogo(f)
      setData(r)
      r.warnings.forEach((w) => toast.info(w))
      toast.success('Logo caricato')
    } catch (e) { toast.error(e) } finally { setBusy(false); if (input.current) input.current.value = '' }
  }
  const saveSettings = async () => {
    try { const r = await api.saveBrandSettings(s); setData(r); setS(r.settings); toast.success('Impostazioni del logo salvate') } catch (e) { toast.error(e) }
  }
  const remove = async () => {
    try { const r = await api.deleteLogo(); setData(r); setConfirm(false); toast.success('Logo eliminato') } catch (e) { toast.error(e) }
  }
  const set = <K extends keyof BrandSettings>(k: K, v: BrandSettings[K]) => setS({ ...s, [k]: v })

  return (
    <>
      <PageHeader title="Brand Kit" subtitle="Il tuo logo, applicato in modo identico a tutti i video (overlay FFmpeg, mai modificato dall'AI)" />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="card space-y-4 p-4">
          <Section title="Logo">
            {kit.logo ? (
              <div className="flex flex-wrap items-center gap-4">
                <div className="grid h-28 w-44 place-items-center rounded-lg bg-[repeating-conic-gradient(#3f3f46_0_25%,#27272a_0_50%)] bg-[length:16px_16px] p-2 ring-1 ring-ink-600">
                  <img src={kit.logo.url} alt="Logo caricato" className="max-h-full max-w-full object-contain" />
                </div>
                <div className="space-y-1 text-sm">
                  <div className="font-medium text-white">{kit.logo.original_name}</div>
                  <div className="text-xs text-zinc-400">{kit.logo.width}×{kit.logo.height} px · {formatBytes(kit.logo.file_size)} · {kit.logo.has_alpha ? 'con trasparenza' : 'senza trasparenza'}</div>
                  <div className="flex gap-2 pt-1">
                    <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={() => input.current?.click()} disabled={busy}><ImageUp size={14} /> Sostituisci</button>
                    {!confirm ? <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={() => setConfirm(true)}><Trash2 size={14} /> Elimina</button>
                      : <button className="btn-danger px-2.5 py-1.5 text-xs" onClick={remove}>Conferma eliminazione</button>}
                  </div>
                </div>
              </div>
            ) : (
              <button onClick={() => input.current?.click()} disabled={busy}
                className="flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed border-ink-600 p-8 text-zinc-400 hover:border-nova-500 hover:text-white">
                {busy ? <Spinner /> : <ImageUp size={28} />}
                <span className="text-sm font-medium">Carica il tuo logo</span>
                <span className="text-xs">PNG con trasparenza · massimo {kit.limits.max_mb} MB · fino a {kit.limits.max_px} px per lato</span>
              </button>
            )}
            <input ref={input} type="file" accept="image/png" className="hidden" onChange={(e) => upload(e.target.files?.[0])} />
            <p className="text-xs text-zinc-500">Il file viene controllato (deve essere davvero un PNG), ricodificato e salvato sul tuo PC in <code>data/brand</code>. I bordi trasparenti vengono rifilati.</p>
          </Section>

          <Section title="Posizione e aspetto">
            <Toggle label="Applica il logo ai video" checked={s.enabled} onChange={(v) => set('enabled', v)} hint="Puoi anche disattivarlo per singola clip nel Clip Editor" />
            <Segmented value={s.position} onChange={(v) => set('position', v)} options={CORNERS} />
            <Slider label="Dimensione" value={s.size} min={0.05} max={0.4} step={0.01} onChange={(v) => set('size', v)} fmt={(v) => `${Math.round(v * 100)}%`} />
            <Slider label="Opacità" value={s.opacity} min={0.1} max={1} step={0.05} onChange={(v) => set('opacity', v)} fmt={(v) => `${Math.round(v * 100)}%`} />
            <Slider label="Margine" value={s.margin} min={0} max={200} step={2} onChange={(v) => set('margin', v)} fmt={(v) => `${v}px`} />
            <Toggle label="Evita le zone dell'interfaccia social" checked={s.safe_area} onChange={(v) => set('safe_area', v)}
              hint="Tiene il logo lontano da barra in alto, didascalia in basso e pulsanti a destra" />
            <button className="btn-primary" disabled={!dirty} onClick={saveSettings}><Save size={15} /> Salva impostazioni</button>
          </Section>
        </div>

        <div className="card p-4 lg:sticky lg:top-6 lg:self-start">
          <h3 className="mb-3 flex items-center gap-2 font-display font-semibold text-white"><Stamp size={16} /> Anteprima 9:16</h3>
          <div className="relative mx-auto aspect-[9/16] w-full max-w-[300px] overflow-hidden rounded-xl bg-gradient-to-b from-ink-700 via-ink-800 to-ink-950 ring-1 ring-ink-600">
            {s.safe_area && <>
              <div className="absolute inset-x-0 top-0 bg-red-500/10" style={{ height: `${(190 / 1920) * 100}%` }} title="Zona barra superiore" />
              <div className="absolute inset-x-0 bottom-0 bg-red-500/10" style={{ height: `${(380 / 1920) * 100}%` }} title="Zona didascalia" />
            </>}
            <div className="absolute inset-x-6 text-center font-black uppercase text-white [text-shadow:0_2px_0_#000]" style={{ top: '60%' }}>Sottotitoli qui</div>
            {kit.logo && box && s.enabled && (
              <img src={kit.logo.url} alt="" className="absolute object-contain"
                style={{ left: `${box.x * 100}%`, top: `${box.y * 100}%`, width: `${box.w * 100}%`, height: `${box.h * 100}%`, opacity: s.opacity }} />
            )}
            {!kit.logo && <div className="absolute inset-0 grid place-items-center text-xs text-zinc-500">Nessun logo</div>}
          </div>
          <p className="mt-3 text-[11px] text-zinc-500">Le aree rosse sono le zone coperte dall'interfaccia di TikTok/Reels/Shorts. Per vedere il logo su un fotogramma vero apri il Clip Editor.</p>
          {dirty && <p className="mt-2 text-xs text-amber-300">Modifiche non salvate</p>}
          <button className="btn-ghost mt-2 px-2 py-1 text-xs" onClick={() => { void reload(); setS(null) }}>Annulla modifiche</button>
        </div>
      </div>
    </>
  )
}
