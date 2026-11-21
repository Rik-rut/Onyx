import { defineConfig } from 'vite';
import { svelte as sveltePlugin, vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';

// Vite builds into frontend/dist; scripts/finalize.mjs copies it to
// src/arr/web/static/dist for the FastAPI server to serve.
export default defineConfig({
  plugins: [
    tailwindcss(),
    sveltePlugin({
      configFile: false,
      preprocess: [vitePreprocess()],
    }),
  ],
  build: {
    outDir: 'dist',
    assetsInlineLimit: 0,
  },
});
