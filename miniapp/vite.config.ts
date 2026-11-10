import react from '@vitejs/plugin-react-swc';
import { defineConfig } from 'vite';

export default defineConfig({
  base: '/miniapp/',
  plugins: [react()],
  server: { proxy: {
    '/miniapp/api': 'http://127.0.0.1:8088',
    '/miniapp/room-preview-api': {
      target: 'http://127.0.0.1:8091',
      rewrite: (path) => path.replace('/miniapp/room-preview-api', ''),
    },
  } },
});
