import {
  BarChart3, Captions, CheckCircle2, Clapperboard, Compass, Film, FolderSync, Gauge, Layers, Rocket, ScanSearch,
  Music2, Settings, Stamp, Users, type LucideIcon,
} from 'lucide-react'

export interface NavItem { to: string; label: string; icon: LucideIcon; hint: string }
export interface NavStage { id: string; index: string; label: string; icon: LucideIcon; items: NavItem[] }

/** Navigation grouped by the real workflow: footage in → clips made → content out → system. */
export const STAGES: NavStage[] = [
  {
    id: 'acquire', index: '01', label: 'Acquisisci', icon: Film, items: [
      { to: '/library', label: 'Libreria', icon: Film, hint: 'Video sorgente e diritti' },
      { to: '/auto-import', label: 'Import automatico', icon: FolderSync, hint: 'Cartelle OBS / ShadowPlay' },
      { to: '/discovery', label: 'Discovery', icon: Compass, hint: 'Cosa funziona ora' },
      { to: '/creators', label: 'Creator', icon: Users, hint: 'Permessi e consensi' },
    ],
  },
  {
    id: 'create', index: '02', label: 'Crea', icon: Clapperboard, items: [
      { to: '/detection', label: 'Clip Detection', icon: ScanSearch, hint: 'Trova i momenti migliori' },
      { to: '/editor', label: 'Clip Editor', icon: Clapperboard, hint: 'Montaggio verticale' },
      { to: '/subtitles', label: 'Sottotitoli', icon: Captions, hint: 'Testo e tempi' },
      { to: '/render', label: 'Render', icon: Layers, hint: 'Coda ed elaborazioni' },
    ],
  },
  {
    id: 'publish', index: '03', label: 'Pubblica', icon: Rocket, items: [
      { to: '/approval', label: 'Approvazione', icon: CheckCircle2, hint: 'Revisione e testi' },
      { to: '/published', label: 'Export e pubblicati', icon: Rocket, hint: 'Pacchetti e storico' },
    ],
  },
  {
    id: 'system', index: '04', label: 'Sistema', icon: Settings, items: [
      { to: '/brand-kit', label: 'Brand Kit', icon: Stamp, hint: 'Logo e watermark' },
      { to: '/audio', label: 'Libreria audio', icon: Music2, hint: 'Musiche ed effetti sonori' },
      { to: '/analytics', label: 'Analytics', icon: BarChart3, hint: 'Produzione e qualità' },
      { to: '/settings', label: 'Impostazioni', icon: Settings, hint: 'Ambiente e manutenzione' },
    ],
  },
]

export const HOME: NavItem = { to: '/', label: 'Regia', icon: Gauge, hint: 'Panoramica' }

export function stageOf(pathname: string): NavStage | undefined {
  return STAGES.find((s) => s.items.some((i) => pathname === i.to || pathname.startsWith(i.to + '/')))
}

export const JOB_SHORT: Record<string, string> = {
  'video.copy_import': 'Import', 'video.probe': 'Lettura', 'video.analyze': 'Analisi', 'render.clip': 'Render',
  'edit.plan': 'Piano AI', 'auto.pipeline': 'Pipeline', 'publish.post': 'Pubblicazione',
}
