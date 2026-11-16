/** @type {import('tailwindcss').Config} */
import animate from 'tailwindcss-animate'

/*
 * NovaClip design system — "sala di montaggio"
 * Graphite neutrals (slightly warm, never blue: footage colours stay true), one accent — the vermilion
 * "tally" light of a camera that is on air — and quiet status colours that always come with an icon/text.
 *
 * Legacy names are kept as aliases so every page picks up the new identity:
 *   ink   → graphite surfaces      nova  → tally (the one accent)      pulse → bone (secondary, neutral)
 */
const graphite = {
  975: '#080807', 950: '#0c0b0a', 900: '#121110', 850: '#171615', 800: '#1d1c1a',
  750: '#242220', 700: '#2c2a27', 600: '#3b3835', 500: '#57534e', 400: '#7a756e',
}
const tally = { 200: '#ffd2c2', 300: '#ffb196', 400: '#ff8a5c', 500: '#ff5a1f', 600: '#e8460d', 700: '#b8350a', 800: '#5c1d07' }
const bone = { 100: '#faf8f4', 200: '#f1ede6', 300: '#e6e0d6', 400: '#cfc7ba', 500: '#ada496', 600: '#857d71' }

export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        border: 'var(--border)',
        input: 'var(--input)',
        ring: 'var(--ring)',
        background: 'var(--background)',
        foreground: 'var(--foreground)',
        primary: { DEFAULT: 'var(--primary)', foreground: 'var(--primary-foreground)' },
        secondary: { DEFAULT: 'var(--secondary)', foreground: 'var(--secondary-foreground)' },
        destructive: { DEFAULT: 'var(--destructive)' },
        muted: { DEFAULT: 'var(--muted)', foreground: 'var(--muted-foreground)' },
        accent: { DEFAULT: 'var(--accent)', foreground: 'var(--accent-foreground)' },
        popover: { DEFAULT: 'var(--popover)', foreground: 'var(--popover-foreground)' },
        card: { DEFAULT: 'var(--card)', foreground: 'var(--card-foreground)' },
        graphite,
        tally,
        bone,
        ink: graphite,
        nova: tally,
        pulse: bone,
        // Tailwind's zinc is a cool grey; pages use it for secondary text → warm it to match graphite
        zinc: { 50: '#faf8f4', 100: '#f1ede6', 200: '#e6e0d6', 300: '#cfc7ba', 400: '#9a948b', 500: '#7a756e',
                600: '#57534e', 700: '#3b3835', 800: '#242220', 900: '#171615', 950: '#0c0b0a' },
        ok: { DEFAULT: '#5fbf8a', dim: '#1f3a2b' },
        warn: { DEFAULT: '#e8b04a', dim: '#3d2f14' },
        err: { DEFAULT: '#f0616d', dim: '#3f1a1e' },
      },
      fontFamily: {
        // emoji fonts last: titles quoted from creators contain emoji, the UI fonts have no glyphs for them
        sans: ['"Geist Variable"', 'Segoe UI', 'system-ui', 'sans-serif', 'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji'],
        display: ['"Archivo Variable"', '"Geist Variable"', 'Segoe UI', 'system-ui', 'sans-serif', 'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji'],
        mono: ['"JetBrains Mono Variable"', 'Cascadia Code', 'Consolas', 'ui-monospace', 'monospace', 'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      borderRadius: {
        // deliberately tight: tools, not toys
        sm: '2px', DEFAULT: '3px', md: '4px', lg: '5px', xl: '6px', '2xl': '8px', '3xl': '10px',
      },
      boxShadow: {
        glow: '0 0 0 1px rgba(255,90,31,.55)',
        'glow-cyan': '0 0 0 1px rgba(230,224,214,.35)',
        pop: '0 12px 32px -12px rgba(0,0,0,.7), 0 0 0 1px rgba(255,255,255,.04)',
      },
      keyframes: {
        tally: { '0%,100%': { opacity: '1' }, '50%': { opacity: '.35' } },
        scan: { from: { transform: 'translateX(-100%)' }, to: { transform: 'translateX(100%)' } },
      },
      animation: {
        tally: 'tally 1.6s ease-in-out infinite',
        scan: 'scan 1.4s linear infinite',
      },
      transitionTimingFunction: { out: 'cubic-bezier(.2,.8,.2,1)' },
    },
  },
  plugins: [animate],
}
