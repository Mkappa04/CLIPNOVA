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
  llm_provider: string
  llm_model: string
  export_copy_dir: string | null
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

// ---------------------------------------------------------------- Milestone 3
export type Layout = 'full' | 'stack' | 'pip' | 'split'
export type SubtitlePresetId = 'clean' | 'gaming' | 'viral'

export interface Region {
  x: number
  y: number
  w: number
  h: number
  source?: 'auto' | 'manual'
  confidence?: number
}

export interface EditConfig {
  layout: Layout
  crop_mode: 'smart' | 'center' | 'fit'
  webcam_region: Region | null
  hide_webcam_in_gameplay: boolean
  pip_corner: 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'
  pip_size: number
  stack_ratio: number
  zoom: boolean
  zoom_strength: number
  transitions: boolean
  remove_silences: boolean
  silence_strategy: 'quiet' | 'no_speech'
  min_silence_s: number
  silence_padding_s: number
  normalize_audio: boolean
  target_lufs: number
  denoise: boolean
  subtitles: boolean
  subtitle_preset: SubtitlePresetId
  subtitle_position: 'auto' | 'top' | 'middle' | 'bottom'
  subtitle_scale: number
  highlight_words: boolean
  intro: boolean
  intro_text: string
  intro_duration: number
  outro: boolean
  outro_text: string
  outro_duration: number
  fps: 30 | 60
  quality: 'draft' | 'standard' | 'high'
}

export interface EditState {
  config: EditConfig
  saved: boolean
  webcam_region: Region | null
  warnings: string[]
}

export interface SubtitlePreset {
  id: SubtitlePresetId
  name: string
  font: string
  size: number
  uppercase: boolean
  primary: string
  highlight: string
  max_words: number
  position: string
  animation: string
}

export interface CueWord { start: number; end: number; word: string }
export interface Cue { start: number; end: number; text: string; words: CueWord[] }

export interface RenderItem {
  id: string
  clip_id: string
  job_id: string | null
  status: 'rendering' | 'completed' | 'failed' | 'cancelled'
  duration: number | null
  file_size: number | null
  width: number
  height: number
  encoder: string
  config: Partial<EditConfig>
  stats: { warnings?: string[]; cut_seconds?: number; speed_x?: number; elapsed_s?: number; cues?: number; layout?: string }
  error: string | null
  created_at: string
  finished_at: string | null
  clip_title: string
  video_title: string
  game: string
  has_thumbnail: boolean
}

export interface WebcamDetection {
  region: Region | null
  frames: number
  face_frames: number
  reason: string
  saved_region: Region | null
}

// ---------------------------------------------------------------- Milestone 4
export type Platform = 'tiktok' | 'instagram' | 'youtube'

export interface ClipContent {
  language: 'it' | 'en'
  title: string
  hook: string
  caption: string
  description: string
  hashtags: string[]
  cta: string
  category?: string
  generated_by?: string
}

export interface ReviewItem {
  clip: Clip
  render: RenderItem | null
  content: ClipContent | null
  review_note: string
  approved_at: string | null
  rights: Record<'non_commercial' | 'commercial', RightsDecision>
  attribution: string
  approval_revoked?: boolean
}

export interface ExportItem {
  id: string
  clip_id: string
  render_id: string | null
  platforms: Platform[]
  purpose: 'commercial' | 'non_commercial'
  path: string
  copied_to: string | null
  rights_snapshot: RightsDecision
  content_snapshot: { content?: ClipContent; platform_texts?: Record<string, { caption?: string; title?: string; description?: string }> }
  created_at: string
  files: string[]
  clip_title: string
  video_title: string
}

export interface ProviderInfo { platform: Platform; name: string; docs_url: string; credential_fields: string[]; notes: string }
export interface PublishingStatus { enabled: boolean; explanation: string; export_copy_dir: string | null; providers: ProviderInfo[] }
export interface SocialAccount { id: string; platform: Platform; display_name: string; status: string; created_at: string; credentials: Record<string, string> }
export interface Publication {
  id: string
  clip_id: string
  export_id: string
  account_id: string
  platform: Platform
  status: 'scheduled' | 'publishing' | 'published' | 'failed' | 'cancelled'
  privacy: 'private' | 'unlisted' | 'public'
  scheduled_at: string
  attempts: number
  max_attempts: number
  next_attempt_at: string | null
  last_error: string | null
  remote_id: string | null
  remote_url: string | null
  log: { at: string; msg: string }[]
  created_at: string
  clip_title: string
}
export interface LlmStatus { provider: string; model: string; available: boolean; models: string[]; reason?: string }

// ---------------------------------------------------------------- Milestone 4B
export interface PipelineCfg { analyze: boolean; language: string; render_top_n: number; min_score: number; detect_webcam: boolean; edit_config: Partial<EditConfig> }
export interface WatchFolderT {
  id: string; name: string; path: string; enabled: boolean; recursive: boolean; extensions: string[]; mode: 'reference' | 'copy'
  game: string; creator_name: string; source: string; rights: Partial<Rights>; pipeline: PipelineCfg; creator_id: string | null
  creator: string | null; exists: boolean; on_windows: boolean; last_scan_at: string | null; last_error: string | null; counts: Record<string, number>
}
export interface WatchedFileT { id: string; folder_id: string; name: string; path: string; size: number; status: string; reason: string; stage: string; video_id: string | null; job_id: string | null; attempts: number; first_seen_at: string; updated_at: string }
export interface AutomationSettingsT { paused: boolean; window: { enabled: boolean; start: string; end: string }; idle_only: boolean; idle_max_cpu: number; idle_max_gpu: number }
export interface AutomationStatus {
  settings: AutomationSettingsT; watcher_running: boolean; watcher_enabled: boolean; poll_s: number; stable_s: number; remux_grace_s: number
  last_tick_at: string | null; last_tick_stats: Record<string, number | boolean>; can_run_now: boolean; blocked_reason: string; counts: Record<string, number>
}
export interface NotificationT { id: string; kind: string; title: string; body: string; link: string; read: boolean; created_at: string }
export interface DiscoveryItem {
  platform: 'youtube' | 'twitch'; kind?: string; id: string; title: string; creator: string; channel_id: string | null; channel_url: string | null
  url: string; published_at: string | null; duration_s: number; is_short?: boolean; views: number; likes: number | null; comments: number | null
  license: string; language: string; thumbnail: string | null; score: number; score_reason: string; attribution_hint?: string
}
export interface DiscoveryCreator { platform: string; channel_id: string | null; name: string; url: string | null; items: number; total_views: number; languages: string[]; latest: string | null; cc_by: number; score: number; score_reason: string }
export interface DiscoveryResult { enabled: boolean; cached?: boolean; cached_at?: string; message?: string; results: DiscoveryItem[]; creators: DiscoveryCreator[]; quota?: { units: number; limit: number; remaining: number; day: string } | null }
export interface DiscoveryStatus { youtube: { configured: boolean; quota: { units: number; limit: number; remaining: number; day: string } }; twitch: { configured: boolean; game: string }; cache_ttl_h: number; policy: string }
export interface PermissionT { id: string; granted_at: string; expires_at: string | null; scope: string; commercial_use: boolean; attribution_text: string; restrictions: string; evidence_text: string; has_evidence_file: boolean; revoked: boolean; valid: boolean; days_left: number | null }
export interface CreatorT {
  id: string; name: string; language: string; channels: { platform: string; channel_id?: string; url?: string; handle?: string }[]; metrics: Record<string, unknown>
  score: number; notes: string; contact: string; status: string; status_label: string; status_history: { at: string | null; from: string | null; to: string; note: string }[]
  source: string; permissions: PermissionT[]; watch_folders: { id: string; path: string; enabled: boolean }[]; created_at: string
}
