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
  'video.analyze': 'Analisi AI + clip detection',
  'render.clip': 'Render verticale 9:16',
  'publish.post': 'Pubblicazione social',
  'auto.pipeline': 'Pipeline automatica (import → render)',
  'edit.plan': 'Piano di montaggio AI',
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

/**
 * Category identity colours: fixed slot order of the validated categorical palette
 * (dark-surface steps, checked against #0a0a12). gameplay_highlight is the neutral "other".
 * Colour always ships with the text label (never colour alone).
 */
export const CATEGORIES: { id: import('../types').ClipCategory; label: string; color: string; emoji: string }[] = [
  { id: 'funny', label: 'Funny', color: '#3987e5', emoji: '😂' },
  { id: 'rage', label: 'Rage', color: '#d95926', emoji: '😡' },
  { id: 'epic', label: 'Epic', color: '#199e70', emoji: '🔥' },
  { id: 'fail', label: 'Fail', color: '#c98500', emoji: '💀' },
  { id: 'reaction', label: 'Reaction', color: '#d55181', emoji: '😱' },
  { id: 'clutch', label: 'Clutch', color: '#0ca30c', emoji: '😮‍💨' },
  { id: 'storytelling', label: 'Storytelling', color: '#9085e9', emoji: '🎙️' },
  { id: 'unexpected', label: 'Unexpected', color: '#e66767', emoji: '🤯' },
  { id: 'gameplay_highlight', label: 'Gameplay Highlight', color: '#8b8b9e', emoji: '⚡' },
]
export const CATEGORY_BY_ID = Object.fromEntries(CATEGORIES.map((c) => [c.id, c]))

export const SIGNAL_LABELS: Record<string, string> = {
  audio_peak: 'Picchi audio',
  audio_energy: 'Energia audio',
  speech_excitement: 'Parlato concitato',
  keywords: 'Keyword',
  laughter: 'Risate',
  visual_motion: 'Movimento',
  scene_changes: 'Cambi scena',
}

export function formatTime(t: number): string {
  const m = Math.floor(t / 60)
  const s = t - m * 60
  return `${m}:${s.toFixed(1).padStart(4, '0')}`
}

export const PLATFORM_LABELS: Record<string, string> = { tiktok: 'TikTok', instagram: 'Instagram Reels', youtube: 'YouTube Shorts' }

export const FILE_STATUS: Record<string, { label: string; tone: 'zinc' | 'cyan' | 'green' | 'amber' | 'red' | 'violet' }> = {
  waiting: { label: 'in attesa', tone: 'zinc' }, ready: { label: 'importato', tone: 'violet' }, deferred: { label: 'rimandato', tone: 'amber' },
  processing: { label: 'in lavorazione', tone: 'cyan' }, done: { label: 'completato', tone: 'green' }, skipped: { label: 'scartato', tone: 'zinc' },
  duplicate: { label: 'duplicato', tone: 'zinc' }, error: { label: 'errore', tone: 'red' },
}
