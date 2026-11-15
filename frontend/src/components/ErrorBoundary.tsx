import { AlertTriangle, RotateCcw } from 'lucide-react'
import { Component, type ErrorInfo, type ReactNode } from 'react'

interface State { error: Error | null }

/** A page crash shows a readable message (and a retry) instead of a blank screen. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('CLIPNOVA page error', error, info.componentStack)
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null })
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="card mx-auto mt-10 max-w-xl border-red-500/40 p-6 text-sm">
        <div className="mb-2 flex items-center gap-2 font-display text-lg font-semibold text-white">
          <AlertTriangle className="text-red-400" size={20} /> Questa pagina ha avuto un errore
        </div>
        <p className="mb-3 text-zinc-400">Gli altri dati non sono stati toccati. Dettaglio tecnico:</p>
        <pre className="mb-4 overflow-x-auto rounded bg-ink-850 p-3 text-xs text-red-200">{this.state.error.message}</pre>
        <button className="btn-ghost" onClick={() => this.setState({ error: null })}><RotateCcw size={14} /> Riprova</button>
      </div>
    )
  }
}
