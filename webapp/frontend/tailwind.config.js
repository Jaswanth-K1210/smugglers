export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        paper: '#0A0A0A',
        surface: '#141414',
        ink: { DEFAULT: '#E8E8E8', 2: '#A3A3A3', 3: '#838383' },
        rule: '#2A2A2A',
        shoal: '#111111',
        signal: { DEFAULT: '#44FF88', dark: '#2FD970' },
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
