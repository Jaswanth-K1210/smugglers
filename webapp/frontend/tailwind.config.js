export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        paper: '#070B0A',
        surface: '#0B1210',
        ink: { DEFAULT: '#D3E2DA', 2: '#8BA197', 3: '#56685F' },
        rule: '#1D2B26',
        shoal: '#0A1512',
        signal: { DEFAULT: '#3BF08A', dark: '#2BC771' },
        // AIS evidence categories; validated as a categorical set on the dark surface
        visible: '#1C93CF',
        partial: '#C77D06',
        unmatched: '#F0306F',
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
}
