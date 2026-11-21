import { svelte as sveltePlugin, vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { svelteTesting } from '@testing-library/svelte/vite';

// Tests compile the same Svelte sources the production build uses, then mount
// them in jsdom through @testing-library/svelte. The jsdom url matches the
// production origin so History-API calls resolve like they do in the browser.
export default {
  plugins: [
    sveltePlugin({
      configFile: false,
      preprocess: [vitePreprocess()],
    }),
    svelteTesting(),
  ],
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'jsdom',
    environmentOptions: {
      jsdom: {
        url: 'http://127.0.0.1:3698/',
      },
    },
  },
};
