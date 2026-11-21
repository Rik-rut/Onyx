import sveltePreprocess from 'svelte-preprocess';

export const config = {
  preprocess: [sveltePreprocess({ typescript: true })],
};

export default config;
