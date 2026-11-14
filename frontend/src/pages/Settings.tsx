import { Cpu, HardDrive, MonitorPlay, Sparkles } from 'lucide-react'
import type { ReactNode } from 'react'
import { Badge, ErrorBox, PageHeader, ProgressBar, Spinner } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { formatBytes } from '../services/format'

function Row({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-ink-800 py-2 text-sm last:border-0">
      <span className="text-zinc-400">{k}</span><span className="text-right text-zinc-100">{v}</span>
    </div>
  )
}

function Panel({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <section className="card p-5">
      <h2 className="mb-3 flex items-center gap-2 font-display font-semibold text-white"><span className="text-nova-400">{icon}</span>{title}</h2>
      {children}
    </section>
  )
}

const yes = (b: boolean | null | undefined, y = 'sì', n = 'no') =>
  b ? <Badge tone="green">{y}</Badge> : <Badge tone={b === null ? 'zinc' : 'red'}>{n}</Badge>

export function Settings() {
  const { data: sys, error, reload } = useApi(() => api.system(), [], 5000)
  const { data: cfg } = useApi(() => api.settings())

  return (
    <>
      <PageHeader title="Settings" subtitle="Ambiente, hardware e configurazione (modificabile in .env)" />
      {error && <ErrorBox error={error} onRetry={reload} />}
      {!sys && !error && <Spinner />}
      {sys && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Panel title="Ambiente" icon={<Cpu size={18} />}>
            <Row k="WSL 2" v={yes(sys.is_wsl2)} />
            <Row k="Distribuzione" v={sys.distro} />
            <Row k="Kernel" v={<span className="font-mono text-xs">{sys.kernel}</span>} />
            <Row k="Python" v={sys.python} />
            <Row k="CPU" v={`${sys.cpu} (${sys.cpu_threads} thread)`} />
            <Row k="RAM" v={`${formatBytes(sys.memory.available)} liberi / ${formatBytes(sys.memory.total)}`} />
          </Panel>

          <Panel title="GPU" icon={<MonitorPlay size={18} />}>
            {sys.gpu.available ? (
              <>
                <Row k="Modello" v={sys.gpu.name} />
                <Row k="Driver (Windows)" v={sys.gpu.driver} />
                <Row k="VRAM" v={`${sys.gpu.memory_used_mb} / ${sys.gpu.memory_total_mb} MB`} />
                <ProgressBar value={(sys.gpu.memory_used_mb ?? 0) / (sys.gpu.memory_total_mb ?? 1)} className="my-2" />
                <Row k="Utilizzo" v={`${sys.gpu.utilization_pct ?? '—'}%`} />
                <Row k="NVENC H.264 (FFmpeg)" v={yes(sys.ffmpeg.nvenc_h264, 'funzionante', 'non disponibile')} />
                <Row k="Limite VRAM CLIPNOVA" v={`${cfg?.max_vram_mb ?? '—'} MB`} />
              </>
            ) : <p className="text-sm text-amber-300">GPU non disponibile: {sys.gpu.reason}. Verrà usata la CPU.</p>}
          </Panel>

          <Panel title="AI runtime" icon={<Sparkles size={18} />}>
            {Object.entries(sys.ai.modules).map(([m, ok]) => <Row key={m} k={m} v={yes(ok, 'installato', 'mancante')} />)}
            <Row k="CUDA (CTranslate2)" v={sys.ai.cuda_available === null ? <Badge>n/d</Badge> : yes(sys.ai.cuda_available, 'attivo', 'CPU')} />
            {sys.ai.whisper && (<>
              <Row k="Whisper GPU" v={`${sys.ai.whisper.gpu_model} (${sys.ai.whisper.gpu_compute})`} />
              <Row k="Whisper CPU (fallback)" v={sys.ai.whisper.cpu_model} />
              <Row k="VRAM minima per GPU" v={`${sys.ai.whisper.min_free_vram_mb} MB`} />
              <Row k="Modelli in cache" v={sys.ai.whisper.cached_models.join(', ') || 'nessuno (download al primo uso)'} />
            </>)}
            <p className="mt-2 text-xs text-zinc-500">Tutto gira in locale. I pesi Whisper vengono scaricati una volta da Hugging Face in data/models.</p>
          </Panel>

          <Panel title="Storage & FFmpeg" icon={<HardDrive size={18} />}>
            <Row k="Cartella dati" v={<span className="break-all font-mono text-xs">{sys.disk.data_dir}</span>} />
            <Row k="Usato da CLIPNOVA" v={formatBytes(sys.disk.data_dir_bytes)} />
            <Row k="Disco libero" v={`${formatBytes(sys.disk.free)} / ${formatBytes(sys.disk.total)}`} />
            <ProgressBar value={sys.disk.used / sys.disk.total} className="my-2" />
            <Row k="FFmpeg" v={<span className="font-mono text-xs">{sys.ffmpeg.ffmpeg?.split(' ').slice(0, 3).join(' ')}</span>} />
            <Row k="HW accel" v={sys.ffmpeg.hwaccels.join(', ') || '—'} />
          </Panel>

          {cfg && (
            <Panel title="Configurazione" icon={<Cpu size={18} />}>
              <Row k="Bind" v={`${cfg.host}:${cfg.port}`} />
              <Row k="Worker paralleli" v={cfg.worker_concurrency} />
              <Row k="GPU abilitata" v={yes(cfg.use_gpu)} />
              <Row k="Lingua predefinita" v={cfg.default_language} />
              <Row k="Upload massimo" v={`${cfg.max_upload_mb} MB`} />
              <Row k="Pubblicazione social" v={cfg.publishing_enabled ? <Badge tone="amber">abilitata</Badge> : <Badge tone="green">disabilitata</Badge>} />
              <Row k="Formati" v={<span className="text-xs">{cfg.supported_extensions.join(' ')}</span>} />
            </Panel>
          )}
        </div>
      )}
    </>
  )
}
