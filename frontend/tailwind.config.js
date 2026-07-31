/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#0b0f14',
          900: '#0f151c',
          850: '#141c26',
          800: '#1a2430',
          700: '#26313f',
          600: '#36455a',
        },
        accent: '#4c8dff',
        allow: '#37d399',
        gate: '#f5b942',
        deny: '#ff6b6b',
      },
      fontFamily: {
        sans: ['Inter var', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
}
