export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
  return `${(bytes / 1024 ** i).toFixed(i >= 2 ? 1 : 0)} ${units[i]}`
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  const s = Math.round(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })
}

export function timeAgo(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return 'adesso'
  if (diff < 3600) return `${Math.floor(diff / 60)} min fa`
  if (diff < 86400) return `${Math.floor(diff / 3600)} h fa`
  return `${Math.floor(diff / 86400)} g fa`
}

export function resolution(w: number | null, h: number | null): string {
  if (!w || !h) return '—'
  const label = h >= 2160 ? '4K' : h >= 1440 ? '1440p' : h >= 1080 ? '1080p' : h >= 720 ? '720p' : `${h}p`
  return `${w}×${h} · ${label}`
}

export const JOB_LABELS: Record<string, string> = {
  'video.probe': 'Analisi metadati',
  'video.copy_import': 'Copia + import',
}

export const LICENSE_LABELS: Record<string, string> = {
  own_content: 'Contenuto proprio',
  creator_permission: 'Permesso del creator',
  licensed: 'Licenza / contratto',
  cc_by: 'Creative Commons BY',
  cc_by_sa: 'Creative Commons BY-SA',
  cc_by_nc: 'Creative Commons BY-NC',
  public_domain: 'Pubblico dominio',
  credit_only: 'Solo credito (NON è un permesso)',
  unknown: 'Sconosciuta',
}

export const AUTH_LABELS: Record<string, string> = {
  authorized: 'Autorizzato',
  pending: 'In attesa',
  denied: 'Negato',
  unknown: 'Sconosciuto',
}
