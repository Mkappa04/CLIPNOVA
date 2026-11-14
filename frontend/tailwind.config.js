/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: { 950: '#05050a', 900: '#0a0a12', 850: '#0f0f1a', 800: '#141422', 700: '#1d1d30', 600: '#2a2a42' },
        nova: { 300: '#c4b5fd', 400: '#a78bfa', 500: '#8b5cf6', 600: '#7c3aed', 700: '#6d28d9' },
        pulse: { 300: '#67e8f9', 400: '#22d3ee', 500: '#06b6d4' },
      },
      fontFamily: {
        sans: ['Inter', 'Segoe UI', 'system-ui', 'sans-serif'],
        display: ['"Space Grotesk"', 'Segoe UI Variable Display', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'Cascadia Code', 'Consolas', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        glow: '0 0 0 1px rgba(139,92,246,.35), 0 8px 30px -8px rgba(139,92,246,.45)',
        'glow-cyan': '0 0 0 1px rgba(34,211,238,.35), 0 8px 30px -8px rgba(34,211,238,.35)',
      },
    },
  },
  plugins: [],
}
