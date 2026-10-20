import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import {defineConfig} from 'vitest/config';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // The Assay tokens use light-dark(). Older targets make the minifier
    // lower it into variables resolved once at :root, which breaks nested
    // data-theme overrides such as the light page in a dark viewer.
    cssTarget: ['chrome123', 'edge123', 'firefox120', 'safari17.5'],
  },
  server: {
    // design-system/ sits beside web/ and holds the Assay theme.
    fs: {allow: ['..']},
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    css: false,
    coverage: {
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}', 'src/main.tsx', 'src/test-setup.ts'],
    },
  },
});
