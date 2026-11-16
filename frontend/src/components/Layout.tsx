import { AnimatePresence, LazyMotion, domAnimation, m as motion } from 'motion/react'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { HOME, JOB_SHORT, STAGES, stageOf, type NavItem, type NavStage } from './nav'
import { NotificationBell } from './Notifications'
import { Toasts } from './Toasts'
import { cx } from './ui'
import { Tip, TooltipProvider } from './ui/tooltip'

// kept for compatibility with any importer of the old flat list
export const NAV = [HOME, ...STAGES.flatMap((s) => s.items)]

/* ------------------------------------------------------------------ brand */
function Mark({ className }: { className?: string }) {
  // a 9:16 frame with the on-air tally light: vertical video, live
  return (
    <svg viewBox="0 0 22 28" className={cx('h-7 w-[22px]', className)} aria-hidden>
      <rect x="1" y="1" width="15" height="26" rx="2" fill="none" stroke="#e6e0d6" strokeWidth="1.6" />
      <path d="M6.5 10.5v7l5.5-3.5z" fill="#e6e0d6" />
      <circle cx="18.5" cy="4" r="3" fill="#ff5a1f" />
    </svg>
  )
}

export function Wordmark({ compact }: { compact?: boolean }) {
  return (
    <Link to="/" className="flex items-center gap-2.5 rounded-sm" aria-label="CLIPNOVA, vai alla regia">
      <Mark />
      {!compact && (
        <span className="display text-[15px] uppercase tracking-[0.08em] text-bone-100" style={{ fontStretch: '125%' }}>
          Clip<span className="text-tally-500">nova</span>
        </span>
      )}
    </Link>
  )
}

/* ------------------------------------------------------------------ status */
function BackendStatus({ compact }: { compact?: boolean }) {
  const { data, error } = useApi(() => api.health(), [], 10000)
  const ok = !!data && !error
  const label = ok ? `Backend v${data.version} attivo` : 'Backend offline'
  const dot = <span className={cx('h-1.5 w-1.5 shrink-0 rounded-full', ok ? 'bg-ok' : 'bg-err animate-tally')} />
  if (compact) return <Tip label={label}><span className="grid h-8 w-8 place-items-center" role="status" aria-label={label}>{dot}</span></Tip>
  return (
    <div className="flex items-center gap-2 font-mono text-2xs text-graphite-400" role="status">
      {dot}<span>{ok ? `v${data.version}` : 'offline'}</span>
    </div>
  )
}

/** Running time of a job (ticks every second): a long AI step never looks frozen. */
function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t) }, [])
  const iso = /Z|[+-]\d\d:\d\d$/.test(since) ? since : since + 'Z'
  const s = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000))
  return <span className="timecode hidden text-2xs text-graphite-400 sm:inline">{Math.floor(s / 60)}:{String(s % 60).padStart(2, '0')}</span>
}

/** Always-visible activity meter: what is being processed right now. */
function JobMonitor() {
  const { data } = useApi(() => api.jobs({ status: 'running,queued', limit: 6 }), [], 2500)
  const jobs = data ?? []
  const running = jobs.filter((j) => j.status === 'running')
  const head = running[0] ?? jobs[0]
  return (
    <Link to="/render" aria-label={jobs.length ? `${jobs.length} elaborazioni in corso` : 'Nessuna elaborazione in corso'}
      className="group flex min-w-0 items-center gap-3 rounded-md px-2 py-1.5 transition-colors hover:bg-graphite-850">
      {head ? (
        <>
          <span className="tally-dot live" />
          <span className="hidden font-mono text-2xs uppercase tracking-[0.12em] text-tally-400 sm:inline">
            {running.length ? 'In corso' : 'In coda'}
          </span>
          <span className="truncate text-xs text-bone-200">
            {JOB_SHORT[head.type] ?? head.type}
            <span className="ml-2 hidden text-graphite-400 md:inline">{head.message}</span>
          </span>
          <span className="relative hidden h-1 w-24 shrink-0 overflow-hidden rounded-full bg-graphite-700 sm:block">
            <span className="absolute inset-y-0 left-0 bg-tally-500 transition-[width] duration-500" style={{ width: `${Math.round(head.progress * 100)}%` }} />
          </span>
          <span className="timecode text-xs text-bone-300">{Math.round(head.progress * 100)}%</span>
          {head.started_at && head.status === 'running' && <Elapsed since={head.started_at} />}
          {jobs.length > 1 && <span className="font-mono text-2xs text-graphite-400">+{jobs.length - 1}</span>}
        </>
      ) : (
        <>
          <span className="h-1.5 w-1.5 rounded-full bg-graphite-500" />
          <span className="font-mono text-2xs uppercase tracking-[0.12em] text-graphite-400">Nessuna elaborazione</span>
        </>
      )}
    </Link>
  )
}

/* ------------------------------------------------------------------ desktop sidebar & tablet rail */
function SideLink({ item, rail }: { item: NavItem; rail?: boolean }) {
  const Icon = item.icon
  const link = (
    <NavLink to={item.to} end={item.to === '/'}
      className={({ isActive }) => cx(
        'group relative flex items-center gap-3 rounded-md text-[13px] transition-colors',
        rail ? 'h-9 w-9 justify-center' : 'px-2.5 py-[7px]',
        isActive ? 'bg-graphite-850 text-bone-100' : 'text-graphite-400 hover:bg-graphite-900 hover:text-bone-200',
      )}>
      {({ isActive }) => (
        <>
          <span className={cx('absolute -left-3 top-1.5 bottom-1.5 w-0.5 rounded-full bg-tally-500 transition-opacity', isActive ? 'opacity-100' : 'opacity-0', rail && '-left-[13px]')} />
          <Icon size={16} strokeWidth={1.75} className={cx('shrink-0', isActive && 'text-tally-500')} />
          {!rail && <span className="truncate">{item.label}</span>}
        </>
      )}
    </NavLink>
  )
  return rail ? <Tip label={<><b className="font-medium">{item.label}</b><span className="ml-2 text-graphite-400">{item.hint}</span></>}>{link}</Tip> : link
}

function Sidebar() {
  return (
    <aside className="sticky top-0 hidden h-dvh w-[232px] shrink-0 flex-col border-r border-graphite-800 bg-graphite-975 lg:flex">
      <div className="flex h-14 items-center px-5"><Wordmark /></div>
      <nav className="flex-1 space-y-6 overflow-y-auto px-3 pb-6 pt-3" aria-label="Navigazione principale">
        <SideLink item={HOME} />
        {STAGES.map((s) => (
          <div key={s.id}>
            <div className="eyebrow mb-1.5 flex items-center gap-2 px-2.5">
              <span className="text-graphite-500">{s.index}</span>{s.label}
            </div>
            <div className="space-y-px">{s.items.map((i) => <SideLink key={i.to} item={i} />)}</div>
          </div>
        ))}
      </nav>
      <div className="flex items-center justify-between border-t border-graphite-800 px-5 py-3">
        <BackendStatus />
        <span className="font-mono text-2xs text-graphite-500">locale · 127.0.0.1</span>
      </div>
    </aside>
  )
}

function Rail() {
  return (
    <aside className="sticky top-0 hidden h-dvh w-16 shrink-0 flex-col items-center border-r border-graphite-800 bg-graphite-975 py-3 md:flex lg:hidden">
      <Wordmark compact />
      <nav className="mt-5 flex flex-1 flex-col items-center gap-1 overflow-y-auto" aria-label="Navigazione principale">
        <SideLink item={HOME} rail />
        {STAGES.map((s) => (
          <div key={s.id} className="flex flex-col items-center gap-1 pt-2">
            <span className="font-mono text-[9px] text-graphite-500">{s.index}</span>
            {s.items.map((i) => <SideLink key={i.to} item={i} rail />)}
          </div>
        ))}
      </nav>
      <BackendStatus compact />
    </aside>
  )
}

/* ------------------------------------------------------------------ mobile: stage tabs + sheet */
function MobileBar() {
  const { pathname } = useLocation()
  const [open, setOpen] = useState<NavStage | null>(null)
  useEffect(() => setOpen(null), [pathname])
  const current = stageOf(pathname)
  return (
    <>
      <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-graphite-800 bg-graphite-975/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
           aria-label="Navigazione">
        <NavLink to="/" end className={({ isActive }) => cx('relative flex flex-col items-center gap-1 py-2.5 text-[10px]', isActive ? 'text-bone-100' : 'text-graphite-400')}>
          {({ isActive }) => <>
            {isActive && <span className="absolute inset-x-5 top-0 h-0.5 bg-tally-500" />}
            <HOME.icon size={18} strokeWidth={1.75} className={isActive ? 'text-tally-500' : ''} />{HOME.label}
          </>}
        </NavLink>
        {STAGES.map((s) => {
          const active = current?.id === s.id
          return (
            <button key={s.id} onClick={() => setOpen(open?.id === s.id ? null : s)} aria-expanded={open?.id === s.id}
              className={cx('relative flex flex-col items-center gap-1 py-2.5 text-[10px]', active || open?.id === s.id ? 'text-bone-100' : 'text-graphite-400')}>
              {active && <span className="absolute inset-x-5 top-0 h-0.5 bg-tally-500" />}
              <s.icon size={18} strokeWidth={1.75} className={active ? 'text-tally-500' : ''} />{s.label}
            </button>
          )
        })}
      </nav>
      <AnimatePresence>
        {open && (
          <>
            <motion.div key="scrim" className="fixed inset-0 z-30 bg-black/60 md:hidden" onClick={() => setOpen(null)}
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }} />
            <motion.div key="sheet" role="dialog" aria-label={open.label}
              className="fixed inset-x-0 bottom-[calc(57px+env(safe-area-inset-bottom))] z-30 border-t border-graphite-700 bg-graphite-900 px-4 pb-4 pt-3 md:hidden"
              initial={{ y: 24, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 16, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 500, damping: 40 }}>
              <div className="eyebrow mb-2"><span className="text-tally-500">{open.index}</span> {open.label}</div>
              <div className="grid grid-cols-2 gap-2">
                {open.items.map((i) => (
                  <NavLink key={i.to} to={i.to}
                    className={({ isActive }) => cx('flex items-start gap-2.5 rounded-md border p-3', isActive ? 'border-tally-500/60 bg-graphite-850' : 'border-graphite-700')}>
                    <i.icon size={16} className="mt-0.5 shrink-0 text-tally-500" />
                    <span><span className="block text-sm text-bone-100">{i.label}</span><span className="block text-2xs text-graphite-400">{i.hint}</span></span>
                  </NavLink>
                ))}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  )
}

/* ------------------------------------------------------------------ shell */
export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation()
  return (
    <LazyMotion features={domAnimation} strict>
    <TooltipProvider>
      <div className="min-h-dvh md:flex">
        <Sidebar />
        <Rail />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-graphite-800 bg-graphite-950/90 px-4 backdrop-blur sm:px-6">
            <div className="md:hidden"><Wordmark compact /></div>
            <div className="min-w-0 flex-1"><JobMonitor /></div>
            <NotificationBell />
          </header>
          <main key={location.pathname}
            className="min-w-0 flex-1 px-4 pb-28 pt-6 duration-200 animate-in fade-in-0 slide-in-from-bottom-1 sm:px-8 sm:pt-8 md:pb-12">
            <div className="mx-auto max-w-[1360px]">{children}</div>
          </main>
        </div>
        <MobileBar />
        <Toasts />
      </div>
    </TooltipProvider>
    </LazyMotion>
  )
}
