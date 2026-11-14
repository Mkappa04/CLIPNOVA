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
  analysis_status: 'running' | 'completed' | 'failed' | null
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
  ai: {
    modules: Record<string, boolean>
    cuda_available: boolean | null
    whisper?: { gpu_model: string; cpu_model: string; gpu_compute: string; min_free_vram_mb: number; keep_loaded: boolean; cached_models: string[] }
  }
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
  whisper_model: string
  whisper_cpu_model: string
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

// ---------------------------------------------------------------- Milestone 2
export type ClipCategory =
  | 'funny' | 'rage' | 'epic' | 'fail' | 'reaction' | 'clutch' | 'storytelling' | 'unexpected' | 'gameplay_highlight'
export type ClipStatus = 'detected' | 'editing' | 'rendering' | 'review' | 'approved' | 'rejected' | 'archived' | 'exported'

export interface Clip {
  id: string
  video_id: string
  start: number
  end: number
  duration: number
  category: ClipCategory
  score: number
  confidence: number
  transcript: string
  reason: string
  suggested_title: string
  status: ClipStatus
  origin: 'auto' | 'manual'
  peak_time: number | null
  language: string
  signals: Record<string, number>
  category_scores: Record<string, number>
  keywords: string[]
  video_title: string
  game: string
  created_at: string
  updated_at: string
}

export interface ScoringWeights {
  audio_peak: number
  audio_energy: number
  speech_excitement: number
  keywords: number
  laughter: number
  visual_motion: number
  scene_changes: number
}

export interface ScoringConfig {
  weights: ScoringWeights
  min_clip_s: number
  max_clip_s: number
  pre_roll_s: number
  post_roll_s: number
  max_clips: number
  min_score: number
  min_gap_s: number
  smoothing_s: number
  reason_language: 'it' | 'en'
}

export interface Analysis {
  status: 'running' | 'completed' | 'failed'
  language: string
  transcription_device: string
  whisper_model: string
  scenes: number[]
  stats: {
    decoder?: string
    media_cached?: boolean
    timings?: Record<string, number>
    audio?: { median_db?: number; peaks?: number; silence_ratio?: number; has_audio?: boolean }
    scenes?: number
    transcript?: { segments: number; words: number; language_probability: number; elapsed_s: number; filtered_hallucinations: number }
  }
  config: Partial<ScoringConfig>
  error: string | null
  updated_at: string
}

export interface TimelineData {
  step_s: number
  interest: number[]
  audio: number[]
  speech: number[]
  motion: number[]
  scenes: number[]
  laughs: number[]
  keywords: { time: number; category: string; keyword: string }[]
}

export interface AnalysisResponse {
  analysis: Analysis | null
  timeline: TimelineData | null
}
