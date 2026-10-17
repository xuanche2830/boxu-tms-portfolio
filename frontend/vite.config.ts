import {defineConfig} from 'vite';
export default defineConfig({
  build: {outDir: '../web', emptyOutDir: true},
  // Backend writes require a same-origin Host. Open the backend URL for complete flows.
  server: {host: '127.0.0.1', proxy: {'/api': {target: 'http://127.0.0.1:8769', changeOrigin: true}}},
});
