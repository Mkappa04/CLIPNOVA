import {
  BarChart3, CheckCircle2, Clapperboard, Film, Gauge, Captions, Layers, Menu, Rocket, ScanSearch, Settings, X,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { Toasts } from './Toasts'
import { cx } from './ui'

export const NAV = [
  { to: '/', label: 'Dashboard', icon: Gauge },
  { to: '/library', label: 'Video Library', icon: Film },
  { to: '/detection', label: 'Clip Detection', icon: ScanSearch },
  { to: '/editor', label: 'Clip Editor', icon: Clapperboard, milestone: 3 },
  { to: '/subtitles', label: 'Subtitle Editor', icon: Captions, milestone: 3 },
  { to: '/render', label: 'Render Queue', icon: Layers },
  { to: '/approval', label: 'Approval Center', icon: CheckCircle2, milestone: 4 },
  { to: '/published', label: 'Published Content', icon: Rocket, milestone: 4 },
  { to: '/analytics', label: 'Analytics', icon: BarChart3, milestone: 5 },
  { to: '/settings', label: 'Settings', icon: Settings },
] as const

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="relative grid h-9 w-9 place-items-center rounded-xl bg-ink-850 ring-1 ring-nova-500/50 shadow-glow">
        <svg viewBox="0 0 24 24" className="h-4 w-4"><defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#a78bfa" /><stop offset="1" stopColor="#22d3ee" /></linearGradient></defs>
          <path d="M7 4l13 8-13 8z" fill="url(#lg)" /></svg>
      </div>
      <div className="leading-tight">
        <div className="font-display text-lg font-bold tracking-[0.18em] text-white">CLIP<span className="text-gradient">NOVA</span></div>
        <div className="text-[10px] uppercase tracking-[0.25em] text-zinc-500">Gaming content engine</div>
      </div>
    </div>
  )
}

function BackendStatus() {
  const { data, error } = useApi(() => api.health(), [], 10000)
  const ok = !!data && !error
  return (
    <div className="flex items-center gap-2 rounded-lg bg-ink-850 px-3 py-2 text-xs ring-1 ring-ink-700">
      <span className={cx('h-2 w-2 rounded-full', ok ? 'bg-emerald-400 shadow-[0_0_8px] shadow-emerald-400' : 'bg-red-500')} />
      <span className="text-zinc-400">{ok ? `Backend v${data.version}` : 'Backend offline'}</span>
    </div>
  )
}

export function Layout({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const location = useLocation()

  const nav = (
    <nav className="flex flex-col gap-1">
      {NAV.map(({ to, label, icon: Icon, ...rest }) => (
        <NavLink key={to} to={to} end={to === '/'} onClick={() => setOpen(false)}
          className={({ isActive }) => cx(
            'group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition',
            isActive ? 'bg-gradient-to-r from-nova-600/30 to-transparent text-white ring-1 ring-nova-500/40'
              : 'text-zinc-400 hover:bg-ink-800 hover:text-zinc-100',
          )}>
          <Icon size={17} className="shrink-0" />
          <span className="flex-1 truncate">{label}</span>
          {'milestone' in rest && <span className="rounded bg-ink-700 px-1.5 text-[10px] text-zinc-500">M{rest.milestone}</span>}
        </NavLink>
      ))}
    </nav>
  )

  return (
    <div className="min-h-screen lg:flex">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col gap-6 border-r border-ink-800 bg-ink-950/80 p-4 backdrop-blur lg:flex">
        <Logo />
        <div className="flex-1 overflow-y-auto">{nav}</div>
        <BackendStatus />
      </aside>

      <header className="sticky top-0 z-40 flex items-center justify-between border-b border-ink-800 bg-ink-950/90 px-4 py-3 backdrop-blur lg:hidden">
        <Logo />
        <button className="btn-ghost px-2" onClick={() => setOpen(true)} aria-label="Apri menu"><Menu size={18} /></button>
      </header>
      {open && (
        <div className="fixed inset-0 z-50 bg-black/70 lg:hidden" onClick={() => setOpen(false)}>
          <div className="flex h-full w-72 flex-col gap-6 bg-ink-950 p-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between"><Logo />
              <button className="btn-ghost px-2" onClick={() => setOpen(false)} aria-label="Chiudi menu"><X size={18} /></button>
            </div>
            {nav}
            <BackendStatus />
          </div>
        </div>
      )}

      <main key={location.pathname} className="min-w-0 flex-1 px-4 py-6 sm:px-8 sm:py-8">
        <div className="mx-auto max-w-7xl">{children}</div>
      </main>
      <Toasts />
    </div>
  )
}
