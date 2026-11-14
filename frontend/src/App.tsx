import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ComingSoon } from './pages/ComingSoon'
import { Dashboard } from './pages/Dashboard'
import { RenderQueue } from './pages/RenderQueue'
import { Settings } from './pages/Settings'
import { VideoLibrary } from './pages/VideoLibrary'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/library" element={<VideoLibrary />} />
        <Route path="/detection" element={<ComingSoon title="Clip Detection" milestone={2} features={[
          'Scene detection (PySceneDetect)', 'Picchi audio e silenzi', 'Trascrizione faster-whisper (GPU/CPU)',
          'Keyword e categorie (Funny, Rage, Epic, Fail…)', 'Score configurabile + confidence', 'Anteprima clip']} />} />
        <Route path="/editor" element={<ComingSoon title="Clip Editor" milestone={3} features={[
          'Export 1080×1920 H.264/AAC', 'Layout gameplay / webcam / PiP / split', 'Smart crop e reframing',
          'Zoom dinamici e transizioni', 'Normalizzazione audio', 'Intro/outro opzionali']} />} />
        <Route path="/subtitles" element={<ComingSoon title="Subtitle Editor" milestone={3} features={[
          'SRT e ASS sincronizzati', 'Evidenziazione parola per parola', 'Preset Clean / Gaming / Viral', 'Safe area social']} />} />
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
