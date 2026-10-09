import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import tailwind from '@tailwindcss/vite';
export default defineConfig(({mode})=>({plugins:[react(),tailwind()],server:{port:5173,proxy:{'/api':mode==='ui-preview'?'http://127.0.0.1:3002':'http://localhost:3000'}},build:{outDir:'../backend/web',emptyOutDir:true}}));
