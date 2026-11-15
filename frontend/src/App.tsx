import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ApprovalCenter } from './pages/ApprovalCenter'
import { AutoImport } from './pages/AutoImport'
import { ClipDetection } from './pages/ClipDetection'
import { ClipEditor } from './pages/ClipEditor'
import { ComingSoon } from './pages/ComingSoon'
import { Creators } from './pages/Creators'
import { Dashboard } from './pages/Dashboard'
import { Discovery } from './pages/Discovery'
import { PublishedContent } from './pages/PublishedContent'
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
        <Route path="/auto-import" element={<AutoImport />} />
        <Route path="/discovery" element={<Discovery />} />
        <Route path="/creators" element={<Creators />} />
        <Route path="/detection" element={<ClipDetection />} />
        <Route path="/editor" element={<ClipEditor />} />
        <Route path="/subtitles" element={<SubtitleEditor />} />
        <Route path="/render" element={<RenderQueue />} />
        <Route path="/approval" element={<ApprovalCenter />} />
        <Route path="/published" element={<PublishedContent />} />
        <Route path="/analytics" element={<ComingSoon title="Analytics" milestone={5} features={[
          'Statistiche produzione clip', 'Performance per gioco e categoria', 'Tempi di elaborazione']} />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}
