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
      className="group block w-full text-left">
      <div className="relative aspect-video overflow-hidden rounded-md bg-graphite-850 ring-1 ring-inset ring-graphite-800 transition group-hover:ring-graphite-500">
        {video.has_thumbnail ? (
          <img src={api.thumbnailUrl(video)} alt="" loading="lazy" className="h-full w-full object-cover transition-transform duration-500 ease-out group-hover:scale-[1.03]" />
        ) : (
          <div className="grid h-full place-items-center text-zinc-600">
            {video.status === 'error' ? <AlertTriangle className="text-red-400" /> : <Film />}
          </div>
        )}
        <div className="viewfinder absolute inset-2 opacity-0 transition-opacity duration-200 group-hover:opacity-100" />
        <div className="absolute left-2 top-2"><StatusBadge status={video.status} /></div>
        <span className="timecode absolute bottom-2 right-2 rounded-sm bg-black/75 px-1.5 py-0.5 text-[11px] text-bone-100">
          {formatDuration(video.duration)}
        </span>
      </div>
      <div className="space-y-2 pt-2.5">
        <h3 className="line-clamp-2 text-sm font-medium leading-snug text-bone-100 group-hover:text-white" title={video.title}>{video.title}</h3>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone="violet">{video.game}</Badge>
          <RightsPill video={video} />
          {video.storage_mode === 'referenced' && <Badge tone="zinc">Rif.</Badge>}
          {video.clip_count > 0 && <Badge tone="cyan">{video.clip_count} clip</Badge>}
        </div>
        <div className="flex justify-between font-mono text-2xs text-graphite-400">
          <span>{resolution(video.width, video.height)}{video.fps ? ` · ${Math.round(video.fps)} fps` : ''}</span>
          <span>{formatBytes(video.file_size)}</span>
        </div>
      </div>
    </button>
  )
}
