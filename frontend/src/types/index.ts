export type VideoStatus = 'pending' | 'copying' | 'probing' | 'ready' | 'analyzing' | 'analyzed' | 'error'
export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'

export type LicenseType =
  | 'own_content' | 'creator_permission' | 'licensed' | 'cc_by' | 'cc_by_sa' | 'cc_by_nc'
  | 'public_domain' | 'credit_only' | 'unknown'
export type AuthorizationStatus = 'authorized' | 'pending' | 'denied' | 'unknown'
export type Purpose = 'internal' | 'non_commercial' | 'commercial'

export interface Rights {
  owner: string
  source_url: string
  license_type: LicenseType
  authorization_status: AuthorizationStatus
  commercial_use_allowed: boolean
  attribution_required: boolean
  attribution_text: string
  expires_at: string | null
  restrictions: string
  evidence: string
  updated_at?: string
}

export interface RightsDecision {
  purpose: Purpose
  allowed: boolean
  blockers: string[]
  warnings: string[]
}

export interface Video {
  id: string
  title: string
  original_filename: string
  file_path: string
  storage_mode: 'uploaded' | 'copied' | 'referenced'
  game: string
  creator: string
  source: string
  notes: string
  file_size: number
  duration: number | null
  width: number | null
  height: number | null
  fps: number | null
  video_codec: string | null
  audio_codec: string | null
  has_audio: boolean
  bitrate: number | null
  status: VideoStatus
  error: string | null
  has_thumbnail: boolean
  clip_count: number
  rights: Rights | null
  created_at: string
  updated_at: string
}

export interface Job {
  id: string
  type: string
  status: JobStatus
  progress: number
  message: string
  payload: Record<string, unknown>
  result: Record<string, unknown> | null
  error: string | null
  cancel_requested: boolean
  video_id: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface ImportResult {
  videos: Video[]
  job_ids: string[]
  warnings: string[]
}

export interface DashboardData {
  videos: { total: number; ready: number; errors: number; total_duration: number; by_game: Record<string, number> }
  clips: { total: number; in_review: number; approved: number; by_status: Record<string, number> }
  jobs: { active: number; failed: number; renders_completed: number }
  storage: { data_bytes: number; disk_free: number; disk_total: number }
  recent_videos: Video[]
  recent_jobs: Job[]
}

export interface SystemInfo {
  is_wsl: boolean
  is_wsl2: boolean
  kernel: string
  distro: string
  python: string
  cpu: string
  cpu_threads: number
  memory: { total: number; available: number }
  disk: { total: number; used: number; free: number; data_dir: string; data_dir_bytes: number }
  gpu: {
    available: boolean
    reason?: string
    name?: string
    memory_total_mb?: number
    memory_used_mb?: number
    memory_free_mb?: number
    driver?: string
    utilization_pct?: number | null
  }
  ffmpeg: { ffmpeg: string | null; ffprobe: string | null; nvenc_h264: boolean; hwaccels: string[] }
  ai: { modules: Record<string, boolean>; cuda_available: boolean | null; torch_version?: string }
}

export interface AppSettings {
  app_name: string
  version: string
  host: string
  port: number
  data_dir: string
  log_level: string
  max_upload_mb: number
  worker_concurrency: number
  use_gpu: boolean
  max_vram_mb: number
  default_language: string
  publishing_enabled: boolean
  supported_extensions: string[]
}

export const EMPTY_RIGHTS: Rights = {
  owner: '',
  source_url: '',
  license_type: 'unknown',
  authorization_status: 'unknown',
  commercial_use_allowed: false,
  attribution_required: true,
  attribution_text: '',
  expires_at: null,
  restrictions: '',
  evidence: '',
}
