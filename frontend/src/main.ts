// SPA entry module: mounts the compiled Svelte 5 AppShell into #onyx-root.
import { mount } from 'svelte';
import AppShell from './components/AppShell.svelte';

let container = document.getElementById('onyx-root');
if (!container) {
  container = document.createElement('div');
  container.id = 'onyx-root';
  document.body.appendChild(container);
}

mount(AppShell, { target: container });
