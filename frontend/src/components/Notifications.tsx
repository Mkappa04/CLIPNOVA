import { Bell } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { timeAgo } from '../services/format'
import { toast } from '../stores/toastStore'
import { cx } from './ui'

export function NotificationBell() {
  const { data, reload } = useApi(() => api.notifications(), [], 15000)
  const [open, setOpen] = useState(false)
  const seen = useRef<string | null>(null)
  const nav = useNavigate()

  // toast when a new "clips ready" notification arrives while the dashboard is open
  useEffect(() => {
    const newest = data?.items[0]
    if (!newest) return
    if (seen.current && newest.id !== seen.current && !newest.read && newest.kind === 'review') toast.success(newest.title)
    seen.current = newest.id
  }, [data])

  const readAll = async () => { await api.readNotifications().catch(() => {}); reload() }
  const unread = data?.unread ?? 0
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} aria-label={`Notifiche (${unread} non lette)`} aria-expanded={open}
        className="relative grid h-9 w-9 place-items-center rounded-md text-graphite-400 transition-colors hover:bg-graphite-850 hover:text-bone-100">
        <Bell size={17} strokeWidth={1.75} />
        {unread > 0 && <span className="absolute right-1 top-1 min-w-[15px] rounded-sm bg-tally-500 px-1 font-mono text-[9px] font-semibold leading-[15px] text-[#160800]">{unread > 99 ? '99+' : unread}</span>}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-11 z-50 w-[min(22rem,calc(100vw-2rem))] rounded-lg border border-graphite-700 bg-graphite-900 shadow-pop duration-150 animate-in fade-in-0 slide-in-from-top-1">
            <div className="flex items-center justify-between border-b border-graphite-700 px-3 py-2.5">
              <span className="eyebrow">Notifiche</span>
              {unread > 0 && <button className="text-xs text-bone-300 hover:text-white" onClick={readAll}>Segna come lette</button>}
            </div>
            <ul className="max-h-96 divide-y divide-graphite-800 overflow-y-auto">
              {data?.items.length === 0 && <li className="px-3 py-6 text-xs text-graphite-400">Nessuna notifica.</li>}
              {data?.items.map((n) => (
                <li key={n.id}>
                  <button onClick={() => { setOpen(false); if (n.link) nav(n.link); void readAll() }}
                    className="flex w-full gap-2.5 px-3 py-2.5 text-left text-xs transition-colors hover:bg-graphite-850">
                    <span className={cx('mt-1 h-1.5 w-1.5 shrink-0 rounded-full', n.read ? 'bg-transparent' : 'bg-tally-500')} />
                    <span className="min-w-0">
                      <span className={cx('block', n.read ? 'text-bone-300' : 'font-medium text-bone-100')}>{n.title}</span>
                      {n.body && <span className="block truncate text-graphite-400">{n.body}</span>}
                      <span className="timecode mt-0.5 block text-[10px] text-graphite-500">{timeAgo(n.created_at)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </div>
  )
}
