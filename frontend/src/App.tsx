import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ClipDetection } from './pages/ClipDetection'
import { ClipEditor } from './pages/ClipEditor'
import { ComingSoon } from './pages/ComingSoon'
import { Dashboard } from './pages/Dashboard'
import { RenderQueue } from './pages/RenderQueue'
import { Settings } from './pages/Settings'
import { SubtitleEditor } from './pages/SubtitleEditor'
import { VideoLibrary } from './pages/VideoLibrary'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/library" element={<VideoLibrary />} />
        <Route path="/detection" element={<ClipDetection />} />
        <Route path="/editor" element={<ClipEditor />} />
        <Route path="/subtitles" element={<SubtitleEditor />} />
        <Route path="/render" element={<RenderQueue />} />
        <Route path="/approval" element={<ComingSoon title="Approval Center" milestone={4} features={[
          'Anteprima e modifica timestamp', 'Modifica sottotitoli, caption, hashtag', 'Approva / Rifiuta / Archivia',
          'Blocco export per diritti insufficienti']} />} />
        <Route path="/published" element={<ComingSoon title="Published Content" milestone={4} features={[
          'Export manuale assistito', 'Architettura API ufficiali TikTok / Instagram / YouTube', 'Token cifrati, retry, log, scheduling']} />} />
        <Route path="/analytics" element={<ComingSoon title="Analytics" milestone={5} features={[
          'Statistiche produzione clip', 'Performance per gioco e categoria', 'Tempi di elaborazione']} />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}
