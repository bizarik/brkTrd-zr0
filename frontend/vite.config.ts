import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		proxy: {
			// Browser calls /api → Vite proxies to backend service
			'/api': {
				target: process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000',
				changeOrigin: true
			},
			'/ws': {
				target: (process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000').replace('http://', 'ws://'),
				ws: true
			}
		}
	}
});
