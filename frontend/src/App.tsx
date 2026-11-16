import { Suspense, lazy } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { ErrorBoundary } from './components/ErrorBoundary'
import { Layout } from './components/Layout'
import { Spinner } from './components/ui'
import { Dashboard } from './pages/Dashboard'

// Pages are code-split: each one loads only when opened.
const page = <K extends string>(loader: () => Promise<Record<K, React.ComponentType>>, name: K) =>
  lazy(() => loader().then((m) => ({ default: m[name] })))

const VideoLibrary = page(() => import('./pages/VideoLibrary'), 'VideoLibrary')
const AutoImport = page(() => import('./pages/AutoImport'), 'AutoImport')
const ClipDetection = page(() => import('./pages/ClipDetection'), 'ClipDetection')
const ClipEditor = page(() => import('./pages/ClipEditor'), 'ClipEditor')
const SubtitleEditor = page(() => import('./pages/SubtitleEditor'), 'SubtitleEditor')
const RenderQueue = page(() => import('./pages/RenderQueue'), 'RenderQueue')
const ApprovalCenter = page(() => import('./pages/ApprovalCenter'), 'ApprovalCenter')
const PublishedContent = page(() => import('./pages/PublishedContent'), 'PublishedContent')
const Discovery = page(() => import('./pages/Discovery'), 'Discovery')
const Creators = page(() => import('./pages/Creators'), 'Creators')
const Analytics = page(() => import('./pages/Analytics'), 'Analytics')
const Settings = page(() => import('./pages/Settings'), 'Settings')
const BrandKit = page(() => import('./pages/BrandKit'), 'BrandKit')

export default function App() {
  const location = useLocation()
  return (
    <Layout>
      <ErrorBoundary resetKey={location.pathname}>
        <Suspense fallback={<Spinner />}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/library" element={<VideoLibrary />} />
            <Route path="/auto-import" element={<AutoImport />} />
            <Route path="/detection" element={<ClipDetection />} />
            <Route path="/editor" element={<ClipEditor />} />
            <Route path="/subtitles" element={<SubtitleEditor />} />
            <Route path="/render" element={<RenderQueue />} />
            <Route path="/brand-kit" element={<BrandKit />} />
            <Route path="/approval" element={<ApprovalCenter />} />
            <Route path="/published" element={<PublishedContent />} />
            <Route path="/discovery" element={<Discovery />} />
            <Route path="/creators" element={<Creators />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </ErrorBoundary>
    </Layout>
  )
}
