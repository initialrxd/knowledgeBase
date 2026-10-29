import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  build: {outDir: '../knowledge_service/static', emptyOutDir: true},
  server: {proxy: {'/manager': 'http://127.0.0.1:8767', '/health': 'http://127.0.0.1:8767'}},
});
