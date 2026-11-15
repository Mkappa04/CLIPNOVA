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
      <button onClick={() => setOpen(!open)} aria-label={`Notifiche (${unread} non lette)`}
        className="flex w-full items-center gap-2 rounded-lg bg-ink-850 px-3 py-2 text-xs text-zinc-300 ring-1 ring-ink-700 hover:text-white">
        <Bell size={14} className={unread ? 'text-pulse-400' : ''} />
        <span className="flex-1 text-left">Notifiche</span>
        {unread > 0 && <span className="rounded-full bg-pulse-500 px-1.5 text-[10px] font-bold text-ink-950">{unread}</span>}
      </button>
      {open && (
        <div className="absolute bottom-11 left-0 z-50 w-80 rounded-xl bg-ink-900 p-2 shadow-2xl ring-1 ring-ink-600">
          <div className="mb-1 flex items-center justify-between px-2 py-1">
            <span className="text-sm font-semibold text-white">Notifiche</span>
            {unread > 0 && <button className="text-xs text-pulse-400 hover:underline" onClick={readAll}>Segna come lette</button>}
          </div>
          <ul className="max-h-80 space-y-1 overflow-y-auto">
            {data?.items.length === 0 && <li className="px-2 py-3 text-xs text-zinc-500">Nessuna notifica.</li>}
            {data?.items.map((n) => (
              <li key={n.id}>
                <button onClick={() => { setOpen(false); if (n.link) nav(n.link); void readAll() }}
                  className={cx('w-full rounded-lg px-2 py-1.5 text-left text-xs hover:bg-ink-800', !n.read && 'bg-nova-500/10')}>
                  <div className={cx('text-zinc-200', !n.read && 'font-semibold text-white')}>{n.title}</div>
                  {n.body && <div className="truncate text-zinc-500">{n.body}</div>}
                  <div className="text-[10px] text-zinc-600">{timeAgo(n.created_at)}</div>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
