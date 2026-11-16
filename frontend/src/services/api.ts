import type {
  AutomationSettingsT, AutomationStatus, CreatorT, DiscoveryResult, DiscoveryStatus, NotificationT, WatchFolderT, WatchedFileT,
  ClipContent, ExportItem, LlmStatus, Platform, Publication, PublishingStatus, ReviewItem, SocialAccount,
  Cue, EditConfig, EditState, Region, RenderItem, SubtitlePreset, WebcamDetection,
  BrandKit, BrandSettings, EditPlan, EditingPreset, EditingPresetId, MetadataPart, SocialMetadata,
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
  rerank: (videoId: string) => request<Clip[]>(`/api/videos/${videoId}/rerank`, { method: 'POST' }),
  preferences: () => request<{ positive: number; negative: number; min_positive: number; active: boolean; model: string }>('/api/preferences'),
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

  // ---- editing, subtitles, renders (Milestone 3)
  clip: (id: string) => request<Clip>(`/api/clips/${id}`),
  editState: (clipId: string) => request<EditState>(`/api/clips/${clipId}/edit`),
  saveEdit: (clipId: string, cfg: EditConfig) =>
    request<EditState>(`/api/clips/${clipId}/edit`, { method: 'PUT', body: JSON.stringify(cfg) }),
  async previewFrame(clipId: string, t: number, config: EditConfig, signal?: AbortSignal): Promise<string> {
    const res = await fetch(`/api/clips/${clipId}/preview-frame`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ t, config }), signal,
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new ApiError(res.status, body.error ?? 'http_error', body.message ?? res.statusText)
    }
    return URL.createObjectURL(await res.blob())
  },
  videoFrameUrl: (videoId: string, t: number) => `/api/videos/${videoId}/frame?t=${t.toFixed(2)}`,
  detectWebcam: (videoId: string) => request<WebcamDetection>(`/api/videos/${videoId}/webcam/detect`, { method: 'POST' }),
  setWebcam: (videoId: string, region: Region | null) =>
    request<{ webcam_region: Region | null }>(`/api/videos/${videoId}/webcam`, { method: 'PUT', body: JSON.stringify(region) }),
  subtitlePresets: () => request<SubtitlePreset[]>('/api/subtitles/presets'),
  subtitles: (clipId: string) => request<{ cues: Cue[]; edited: boolean; preset: string; duration: number }>(`/api/clips/${clipId}/subtitles`),
  saveSubtitles: (clipId: string, cues: Cue[]) =>
    request<{ cues: Cue[]; edited: boolean; preset: string; duration: number }>(`/api/clips/${clipId}/subtitles`, { method: 'PUT', body: JSON.stringify({ cues }) }),
  resetSubtitles: (clipId: string) =>
    request<{ cues: Cue[]; edited: boolean; preset: string; duration: number }>(`/api/clips/${clipId}/subtitles${qs({ confirm: true })}`, { method: 'DELETE' }),
  subtitleExportUrl: (clipId: string, format: 'srt' | 'ass') => `/api/clips/${clipId}/subtitles/export?format=${format}`,
  render: (clipId: string, config: EditConfig) =>
    request<{ job_id: string }>(`/api/clips/${clipId}/render`, { method: 'POST', body: JSON.stringify({ config }) }),
  renders: (filters: { clip_id?: string; status?: string; limit?: number } = {}) => request<RenderItem[]>(`/api/renders${qs(filters)}`),
  deleteRender: (id: string) => request<{ deleted: string }>(`/api/renders/${id}${qs({ confirm: true })}`, { method: 'DELETE' }),
  renderFileUrl: (id: string, download = false) => `/api/renders/${id}/file${download ? '?download=true' : ''}`,
  renderThumbUrl: (id: string) => `/api/renders/${id}/thumbnail`,
  renderSubsUrl: (id: string, format: 'srt' | 'ass') => `/api/renders/${id}/subtitles?format=${format}`,

  // ---- editing presets, AI editing planner, SFX, Brand Kit
  editingPresets: () => request<EditingPreset[]>('/api/editing/presets'),
  selectPreset: (clipId: string, preset: EditingPresetId) =>
    request<EditState>(`/api/clips/${clipId}/preset`, { method: 'PUT', body: JSON.stringify({ preset }) }),
  planPreview: (clipId: string, config: EditConfig, signal?: AbortSignal) =>
    request<{ plan: EditPlan; stored: boolean }>(`/api/clips/${clipId}/edit-plan/preview`, { method: 'POST', body: JSON.stringify({ config }), signal }),
  makePlan: (clipId: string, config: EditConfig) =>
    request<{ job_id: string }>(`/api/clips/${clipId}/edit-plan`, { method: 'POST', body: JSON.stringify({ force: true, config }) }),
  sfxLibrary: () => request<{ category: string; available: boolean; source: string; name: string | null }[]>('/api/sfx'),
  brandKit: () => request<BrandKit>('/api/brand-kit'),
  saveBrandSettings: (s: BrandSettings) => request<BrandKit>('/api/brand-kit/settings', { method: 'PUT', body: JSON.stringify(s) }),
  uploadLogo: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<BrandKit>('/api/brand-kit/logo', { method: 'POST', body: fd })
  },
  deleteLogo: () => request<BrandKit>(`/api/brand-kit/logo${qs({ confirm: true })}`, { method: 'DELETE' }),

  // ---- approval, export, publishing (Milestone 4)
  approvalQueue: (status: string) => request<ReviewItem[]>(`/api/approval/queue${qs({ status })}`),
  approvalCounts: () => request<Record<string, number>>('/api/approval/counts'),
  review: (clipId: string) => request<ReviewItem>(`/api/clips/${clipId}/review`),
  generateContent: (clipId: string, useLlm: boolean, language?: string, parts?: MetadataPart[], current?: SocialMetadata | null) =>
    request<{ content: ClipContent; warnings: string[] }>(`/api/clips/${clipId}/content/generate`, {
      method: 'POST', body: JSON.stringify({ use_llm: useLlm, language, parts: parts ?? null, current: current ?? null }) }),
  saveContent: (clipId: string, content: ClipContent) =>
    request<ReviewItem>(`/api/clips/${clipId}/content`, { method: 'PUT', body: JSON.stringify(content) }),
  reviewAction: (clipId: string, action: 'approve' | 'reject' | 'archive' | 'reopen', note = '') =>
    request<ReviewItem>(`/api/clips/${clipId}/${action}`, { method: 'POST', body: JSON.stringify({ note }) }),
  regenerate: (clipId: string) => request<{ job_id: string }>(`/api/clips/${clipId}/regenerate`, { method: 'POST' }),
  llmStatus: () => request<LlmStatus>('/api/llm/status'),
  createExport: (clipId: string, platforms: Platform[], purpose: 'commercial' | 'non_commercial') =>
    request<ExportItem>(`/api/clips/${clipId}/export`, { method: 'POST', body: JSON.stringify({ platforms, purpose }) }),
  exports: (filters: { clip_id?: string; limit?: number } = {}) => request<ExportItem[]>(`/api/exports${qs(filters)}`),
  exportFileUrl: (id: string, name: string) => `/api/exports/${id}/files/${encodeURIComponent(name)}`,
  deleteExport: (id: string) => request<{ deleted: string }>(`/api/exports/${id}${qs({ confirm: true })}`, { method: 'DELETE' }),
  publishingStatus: () => request<PublishingStatus>('/api/publishing/status'),
  accounts: () => request<SocialAccount[]>('/api/publishing/accounts'),
  addAccount: (platform: Platform, display_name: string, credentials: Record<string, string>) =>
    request<SocialAccount>('/api/publishing/accounts', { method: 'POST', body: JSON.stringify({ platform, display_name, credentials }) }),
  deleteAccount: (id: string) => request<{ deleted: string }>(`/api/publishing/accounts/${id}${qs({ confirm: true })}`, { method: 'DELETE' }),
  publications: () => request<Publication[]>('/api/publishing/publications'),
  schedulePublication: (body: { export_id: string; account_id: string; scheduled_at?: string; privacy: string; confirm: boolean }) =>
    request<Publication>('/api/publishing/publications', { method: 'POST', body: JSON.stringify(body) }),
  cancelPublication: (id: string) => request<Publication>(`/api/publishing/publications/${id}/cancel`, { method: 'POST' }),
  retryPublication: (id: string) => request<Publication>(`/api/publishing/publications/${id}/retry`, { method: 'POST' }),

  // ---- automation, discovery, creators (Milestone 4B)
  automationStatus: () => request<AutomationStatus>('/api/automation/status'),
  saveAutomation: (s: AutomationSettingsT) => request<AutomationStatus>('/api/automation/settings', { method: 'PUT', body: JSON.stringify(s) }),
  scanNow: () => request<Record<string, number>>('/api/automation/scan', { method: 'POST' }),
  watchFolders: () => request<WatchFolderT[]>('/api/watch-folders'),
  addWatchFolder: (body: Record<string, unknown>) => request<WatchFolderT>('/api/watch-folders', { method: 'POST', body: JSON.stringify(body) }),
  updateWatchFolder: (id: string, body: Record<string, unknown>) => request<WatchFolderT>(`/api/watch-folders/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteWatchFolder: (id: string) => request<{ deleted: string }>(`/api/watch-folders/${id}${qs({ confirm: true })}`, { method: 'DELETE' }),
  watchedFiles: (filters: { folder_id?: string; status?: string; limit?: number } = {}) => request<WatchedFileT[]>(`/api/watch-folders/files${qs(filters)}`),
  retryWatchedFile: (id: string) => request<{ status: string }>(`/api/watch-folders/files/${id}/retry`, { method: 'POST' }),
  notifications: () => request<{ unread: number; items: NotificationT[] }>('/api/notifications'),
  readNotifications: () => request<{ unread: number }>('/api/notifications/read', { method: 'POST' }),
  discoveryStatus: () => request<DiscoveryStatus>('/api/discovery/status'),
  discoveryKeys: () => request<Record<string, Record<string, string>>>('/api/discovery/keys'),
  saveDiscoveryKeys: (provider: string, values: Record<string, string>) =>
    request<{ configured: boolean; keys: Record<string, string> }>('/api/discovery/keys', { method: 'PUT', body: JSON.stringify({ provider, values }) }),
  discover: (body: Record<string, unknown>) => request<DiscoveryResult>('/api/discovery/search', { method: 'POST', body: JSON.stringify(body) }),
  creators: () => request<CreatorT[]>('/api/creators'),
  addCreator: (body: Record<string, unknown>) => request<CreatorT>('/api/creators', { method: 'POST', body: JSON.stringify(body) }),
  updateCreator: (id: string, body: Record<string, unknown>) => request<CreatorT>(`/api/creators/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteCreator: (id: string) => request<{ deleted: string }>(`/api/creators/${id}${qs({ confirm: true })}`, { method: 'DELETE' }),
  permissionMessage: (id: string, body: Record<string, unknown>) =>
    request<{ text: string; generated_by: string; warnings: string[]; note: string }>(`/api/creators/${id}/message`, { method: 'POST', body: JSON.stringify(body) }),
  addPermission: (id: string, form: FormData) => request<CreatorT>(`/api/creators/${id}/permissions`, { method: 'POST', body: form }),
  revokePermission: (id: string, pid: string) => request<CreatorT>(`/api/creators/${id}/permissions/${pid}/revoke`, { method: 'POST' }),
  evidenceUrl: (id: string, pid: string) => `/api/creators/${id}/permissions/${pid}/evidence`,
  creatorFolder: (id: string, path: string) => request<CreatorT>(`/api/creators/${id}/watch-folder`, { method: 'POST', body: JSON.stringify({ path }) }),

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
