import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		proxy: {
			// Browser calls /api → Vite proxies to backend service
			'/api': {
				target: process.env.PUBLIC_API_URL || (process.env.NODE_ENV === 'development' ? 'http://localhost:8000' : 'http://backend:8000'),
				changeOrigin: true
			},
			'/ws': {
				target: process.env.PUBLIC_API_URL?.replace('http://', 'ws://') || (process.env.NODE_ENV === 'development' ? 'ws://localhost:8000' : 'ws://backend:8000'),
				ws: true
			}
		}
	}
});
