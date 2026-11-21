import { expect, test } from 'vitest';
import { render } from '@testing-library/svelte';
import AppShell from '../src/components/AppShell.svelte';
import { navigate, setLocation } from '../src/lib/router.svelte';
import { acceptMessage, backendDown, refreshFromRest, retryDelayMs } from '../src/lib/stores/queue.svelte';
import { setSidebarCollapsed, sidebarCollapsed } from '../src/lib/stores/ui.svelte';

// Svelte schedules dirty reactions in microtasks; awaiting one microtask lets
// the queued re-runs flush before the DOM is asserted.
declare const globalThis: {
  fetch: (path: string) => {
    ok: boolean;
    status: number;
    statusText: string;
    text: () => Promise<string>;
  };
  window: {
    history: {
      pushState: (state: Record<string, never>, title: string, target: string) => void;
    };
  };
  localStorage?: {
    getItem: (key: string) => string | null;
    setItem: (key: string, value: string) => void;
  };
};

const flush = async () => await null;

const realFetch = globalThis.fetch;

// jsdom's WebSocket shim rejects asynchronously for real ws:// endpoints;
// these shell tests exercise REST-only rendering and the transfer strip.
globalThis.WebSocket = null as unknown as typeof WebSocket;

test('a reload of a deep link resolves the same view', async () => {
  // The jsdom environment starts at '/', then History-API moves the location.
  globalThis.window.history.pushState({}, '', '/queue');
  const rendered = render(AppShell);
  expect(rendered.container.querySelector('[data-testid="view-label"]').textContent).toBe('Queue');
  expect(rendered.container.querySelector('[data-nav="/queue"]').getAttribute('aria-current')).toBe('page');
});

test('aria-current follows the active route', async () => {
  const rendered = render(AppShell);
  setLocation('/library', '');
  await flush();
  expect(rendered.container.querySelector('[data-nav="/library"]').getAttribute('aria-current')).toBe('page');
  expect(rendered.container.querySelector('[data-nav="/queue"]').hasAttribute('aria-current')).toBe(false);
  navigate('/movies');
  await flush();
  expect(rendered.container.querySelector('[data-nav="/movies"]').getAttribute('aria-current')).toBe('page');
  expect(rendered.container.querySelector('[data-testid="view-label"]').textContent).toBe('Movies');
});

test('collapse toggle persists the preference', async () => {
  const written: Record<string, string> = {};
  globalThis.localStorage = {
    getItem: (key: string) => written[key],
    setItem: (key: string, value: string) => void (written[key] = value),
  } as typeof globalThis.localStorage;
  expect(sidebarCollapsed()).toBe(false);
  const rendered = render(AppShell);
  const toggle = rendered.container.querySelector('[data-testid="sidebar-collapse-toggle"]');
  expect(toggle.getAttribute('title')).toContain('icon rail');
  toggle.click();
  await flush();
  expect(sidebarCollapsed()).toBe(true);
  expect(written['onyx.sidebar-collapsed']).toBe('true');
  // Rail mode: icons only, labels become screen-reader text.
  expect(rendered.container.querySelector('[data-nav="/library"] span.sr-only')).toBeTruthy();
});

test('footer shows live transfer rates without a refresh', async () => {
  acceptMessage(JSON.stringify({
    timestamp: 1_700_000_000,
    torrents: [
      { rate_download: 250, rate_upload: 0 },
      { rate_download: 0, rate_upload: 40 },
    ],
  }));
  const rendered = render(AppShell);
  await flush();
  expect(rendered.container.querySelector('[data-testid="transfer-download"]')?.textContent).toContain('250 B/s');
  expect(rendered.container.querySelector('[data-testid="transfer-upload"]')?.textContent).toContain('40 B/s');
  // No browser WebSocket in this environment: the footer reports the REST
  // fallback while still showing live rates from the accepted message.
  expect(rendered.container.querySelector('[data-testid="connection-dot"]')?.getAttribute('data-connected')).toBe('false');
});

test('a dead backend raises the stale-data banner and grows the backoff', async () => {
  globalThis.fetch = (path: string) => {
    const response = { ok: false, status: 503, statusText: 'down', text: async () => '' };
    return response;
  };
  await refreshFromRest();
  await refreshFromRest();
  await refreshFromRest();
  expect(backendDown()).toBe(true);
  expect(retryDelayMs()).toBe(8000);
  const rendered = render(AppShell);
  const banner = rendered.container.querySelector('[data-testid="backend-banner"]');
  expect(banner).toBeTruthy();
  expect(banner.textContent).toContain('stale');
  globalThis.fetch = realFetch;
});
