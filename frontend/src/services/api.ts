import type {
  AnalysisResponse, Clip, ClipCategory, ClipStatus, ScoringConfig,
  AppSettings, DashboardData, ImportResult, Job, Purpose, Rights, RightsDecision, SystemInfo, Video,
} from '../types'

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message)
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  let res: Response
  try {
    res = await fetch(path, { ...init, headers })
  } catch {
    throw new ApiError(0, 'network', 'Backend non raggiungibile. CLIPNOVA è avviato? (./start.sh)')
  }
  const text = await res.text()
  const data = text ? safeJson(text) : null
  if (!res.ok) {
    const body = (data ?? {}) as { error?: string; message?: string; details?: unknown }
    throw new ApiError(res.status, body.error ?? 'http_error', body.message ?? res.statusText, body.details)
  }
  return data as T
}

function safeJson(text: string): unknown {
  try { return JSON.parse(text) } catch { return text }
}

const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') p.set(k, String(v)) })
  const s = p.toString()
  return s ? `?${s}` : ''
}

export interface UploadMeta {
  game: string
  creator: string
  source: string
  notes: string
  rights: Rights
}

export const api = {
  health: () => request<{ status: string; version: string }>('/api/health'),
  system: () => request<SystemInfo>('/api/system'),
  settings: () => request<AppSettings>('/api/settings'),
  dashboard: () => request<DashboardData>('/api/dashboard'),

  videos: (filters: { q?: string; game?: string; status?: string } = {}) =>
    request<Video[]>(`/api/videos${qs(filters)}`),
  games: () => request<string[]>('/api/videos/games'),
  video: (id: string) => request<Video>(`/api/videos/${id}`),
  updateVideo: (id: string, body: Partial<Pick<Video, 'title' | 'game' | 'creator' | 'source' | 'notes'>>) =>
    request<Video>(`/api/videos/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteVideo: (id: string, deleteFile: boolean) =>
    request<{ removed_files: string[]; kept_files: string[] }>(
      `/api/videos/${id}${qs({ confirm: true, delete_file: deleteFile })}`, { method: 'DELETE' }),
  reprobe: (id: string) => request<{ job_id: string }>(`/api/videos/${id}/reprobe`, { method: 'POST' }),
  importPath: (body: UploadMeta & { path: string; mode: 'reference' | 'copy'; title?: string }) =>
    request<ImportResult>('/api/videos/import-path', { method: 'POST', body: JSON.stringify(body) }),
  putRights: (id: string, rights: Rights) =>
    request<Rights>(`/api/videos/${id}/rights`, { method: 'PUT', body: JSON.stringify(rights) }),
  checkRights: (id: string, purpose: Purpose) =>
    request<RightsDecision>(`/api/videos/${id}/rights/check${qs({ purpose })}`),

  thumbnailUrl: (v: Video) => `/api/videos/${v.id}/thumbnail?v=${encodeURIComponent(v.updated_at)}`,
  streamUrl: (id: string) => `/api/videos/${id}/stream`,

  jobs: (filters: { status?: string; video_id?: string; limit?: number } = {}) =>
    request<Job[]>(`/api/jobs${qs(filters)}`),
  cancelJob: (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' }),

  // ---- analysis & clips (Milestone 2)
  analyze: (videoId: string, body: { language: 'auto' | 'it' | 'en'; transcribe: boolean; force: boolean; scoring?: ScoringConfig }) =>
    request<{ job_id: string }>(`/api/videos/${videoId}/analyze`, { method: 'POST', body: JSON.stringify(body) }),
  analysis: (videoId: string) => request<AnalysisResponse>(`/api/videos/${videoId}/analysis`),
  rescore: (videoId: string, cfg: ScoringConfig) =>
    request<Clip[]>(`/api/videos/${videoId}/detect`, { method: 'POST', body: JSON.stringify(cfg) }),
  scoringDefaults: () => request<{ config: ScoringConfig; weights_help: Record<string, string> }>('/api/scoring/defaults'),
  transcriptUrl: (videoId: string, format: 'srt' | 'txt' | 'json') => `/api/videos/${videoId}/transcript?format=${format}`,
  clips: (filters: { video_id?: string; category?: string; status?: string; sort?: string } = {}) =>
    request<Clip[]>(`/api/clips${qs(filters)}`),
  updateClip: (id: string, body: Partial<{ start: number; end: number; category: ClipCategory; suggested_title: string; status: ClipStatus }>) =>
    request<Clip>(`/api/clips/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  createClip: (videoId: string, body: { start: number; end: number; category: ClipCategory; suggested_title?: string }) =>
    request<Clip>(`/api/videos/${videoId}/clips`, { method: 'POST', body: JSON.stringify(body) }),
  deleteClip: (id: string) => request<{ deleted: string }>(`/api/clips/${id}${qs({ confirm: true })}`, { method: 'DELETE' }),
  previewUrl: (c: Clip) => `/api/clips/${c.id}/preview?v=${c.start}-${c.end}`,

  /** Upload with progress (fetch has no upload progress, so XHR). */
  upload(files: File[], meta: UploadMeta, onProgress: (fraction: number) => void,
         signal?: AbortSignal): Promise<ImportResult> {
    return new Promise((resolve, reject) => {
      const form = new FormData()
      files.forEach((f) => form.append('files', f))
      form.append('game', meta.game)
      form.append('creator', meta.creator)
      form.append('source', meta.source)
      form.append('notes', meta.notes)
      form.append('rights', JSON.stringify(meta.rights))
      const xhr = new XMLHttpRequest()
      xhr.open('POST', '/api/videos/upload')
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total) }
      xhr.onload = () => {
        const data = safeJson(xhr.responseText) as ImportResult & { error?: string; message?: string }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data)
        else reject(new ApiError(xhr.status, data?.error ?? 'http_error', data?.message ?? xhr.statusText))
      }
      xhr.onerror = () => reject(new ApiError(0, 'network', 'Upload fallito: backend non raggiungibile'))
      xhr.onabort = () => reject(new ApiError(0, 'aborted', 'Upload annullato'))
      signal?.addEventListener('abort', () => xhr.abort())
      xhr.send(form)
    })
  },
}
