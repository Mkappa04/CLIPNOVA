import { AlertTriangle, Film, ShieldCheck, ShieldX } from 'lucide-react'
import { api } from '../services/api'
import { formatBytes, formatDuration, resolution } from '../services/format'
import type { Video } from '../types'
import { Badge, StatusBadge } from './ui'

export function RightsPill({ video }: { video: Video }) {
  const r = video.rights
  if (!r || r.authorization_status !== 'authorized' || r.license_type === 'credit_only' || r.license_type === 'unknown')
    return <Badge tone="red"><ShieldX size={11} /> Diritti</Badge>
  return <Badge tone="green"><ShieldCheck size={11} /> Autorizzato</Badge>
}

export function VideoCard({ video, onOpen }: { video: Video; onOpen: () => void }) {
  return (
    <button onClick={onOpen}
      className="card group overflow-hidden text-left transition hover:-translate-y-0.5 hover:border-nova-500/60 hover:shadow-glow">
      <div className="relative aspect-video bg-ink-850">
        {video.has_thumbnail ? (
          <img src={api.thumbnailUrl(video)} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <div className="grid h-full place-items-center text-zinc-600">
            {video.status === 'error' ? <AlertTriangle className="text-red-400" /> : <Film />}
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-ink-950/90 via-transparent" />
        <div className="absolute left-2 top-2"><StatusBadge status={video.status} /></div>
        <span className="absolute bottom-2 right-2 rounded bg-black/70 px-1.5 py-0.5 font-mono text-xs text-white">
          {formatDuration(video.duration)}
        </span>
      </div>
      <div className="space-y-2 p-3">
        <h3 className="truncate font-medium text-white" title={video.title}>{video.title}</h3>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone="violet">{video.game}</Badge>
          <RightsPill video={video} />
          {video.storage_mode === 'referenced' && <Badge tone="zinc">Rif.</Badge>}
          {video.clip_count > 0 && <Badge tone="cyan">{video.clip_count} clip</Badge>}
        </div>
        <div className="flex justify-between text-xs text-zinc-500">
          <span>{resolution(video.width, video.height)}{video.fps ? ` · ${Math.round(video.fps)} fps` : ''}</span>
          <span>{formatBytes(video.file_size)}</span>
        </div>
      </div>
    </button>
  )
}
