import { defineConfig } from 'vite';
// The dev server proxies the API of the service on LPC_LAB_PORT (8765 practice, 8879 development).
const backend = `http://127.0.0.1:${process.env.LPC_LAB_PORT || '8765'}`;
export default defineConfig({
  root: '.',
  server: { proxy: {
    '/api':backend,
    '/board':backend,
    '/assets/board.jpg':backend
  }},
  build: { outDir: 'dist', emptyOutDir:true, chunkSizeWarningLimit: 1600 }
});
