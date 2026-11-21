import { expect, test } from 'vitest';
import { render } from '@testing-library/svelte';
import { flushSync } from 'svelte';
import ConfirmDialog from '../src/components/ConfirmDialog.svelte';
import MonitoredPage from '../src/components/MonitoredPage.svelte';
import { invalidate, refresh } from '../src/lib/stores/library.svelte';
import { currentPath, setLocation } from '../src/lib/router.svelte';
import { confirmation } from '../src/lib/stores/ui.svelte';
import type { LibraryShow, SeriesRow } from '../src/lib/api';

declare const globalThis: {
  fetch: (
    path: string,
    options?: { method?: string; headers?: Record<string, string>; body?: string },
  ) => {
    ok: boolean;
    status: number;
    statusText: string;
    text: () => Promise<string>;
  };
};
// jsdom has no scrollTo implementation; route changes are asserted via currentPath().
Object.defineProperty(window, 'scrollTo', { value: () => {}, configurable: true });

const realFetch = globalThis.fetch;

// Mocked fetch, api awaits and Svelte's re-render all settle in microtasks.
const settle = async () => {
  for (let round = 0; round < 40; round += 1) await null;
};

function ok(body: unknown) {
  return { ok: true, status: 200, statusText: 'OK', text: async () => JSON.stringify(body) };
}

let libraryShows: LibraryShow[] = [];
let seriesRows: SeriesRow[] = [];
let calls: string[] = [];

function serve(): void {
  globalThis.fetch = (path: string, options?: { method?: string }) => {
    const method = options?.method ?? 'GET';
    calls.push(`${method} ${path}`);
    if (method === 'DELETE' && path.startsWith('/api/series/')) {
      const seriesId = Number(path.slice('/api/series/'.length));
      seriesRows = seriesRows.filter((row) => row.id !== seriesId);
      return ok({ status: 'unmonitored' });
    }
    if (path === '/api/library') return ok({ movies: [], shows: libraryShows, sync: {} });
    if (path === '/api/series') return ok(seriesRows);
    return { ok: false, status: 404, statusText: 'Not Found', text: async () => '{"detail":"no data"}' };
  };
}

function show(overrides: Partial<LibraryShow>): LibraryShow {
  return {
    name: '',
    title: '',
    year: null,
    path: '',
    seasons_count: 1,
    episodes_count: 0,
    monitored_count: 0,
    missing: [],
    monitored: true,
    monitored_id: null,
    tmdb_id: null,
    seeding: false,
    poster: '',
    ...overrides,
  };
}

async function seed(): Promise<void> {
  libraryShows = [
    show({ title: 'The Bridge', name: 'the bridge (2016)', tmdb_id: 1403, monitored_id: 12, poster: '/art/bridge.jpg' }),
    show({ title: 'Harbor Lights', name: 'harbor lights (2014)', tmdb_id: 1404, monitored_id: 13 }),
  ];
  seriesRows = [
    {
      id: 12,
      tmdb_id: 1403,
      imdb_id: 'tt500',
      title: 'The Bridge',
      status: 'continuing',
      quality: 'HD-1080p',
      total_episodes: 18,
      imported_episodes: 12,
      missing_episodes: 6,
    },
    {
      id: 13,
      tmdb_id: 1404,
      imdb_id: 'tt600',
      title: 'Harbor Lights',
      status: 'ended',
      quality: '4K-2160p',
      total_episodes: 8,
      imported_episodes: 8,
      missing_episodes: 0,
    },
  ];
  serve();
  invalidate();
  await refresh();
  calls.length = 0;
}

function texts(container: HTMLElement, name: string): string[] {
  return Array.from(container.querySelectorAll(`[data-testid="${name}"]`)).map((node) => node.textContent?.trim() ?? '');
}

function card(container: HTMLElement, seriesId: number): HTMLElement {
  return container.querySelector(`[data-testid="monitored-card"][data-series-id="${seriesId}"]`) as HTMLElement;
}

test('cards render cached poster art, progress bars and missing badges', async () => {
  setLocation('/monitored');
  await seed();

  const rendered = render(MonitoredPage);
  await settle();

  expect(calls).toEqual(['GET /api/series']);
  expect(rendered.container.querySelectorAll('[data-testid="monitored-card"]')).toHaveLength(2);
  expect(texts(rendered.container, 'card-title')).toEqual(['The Bridge', 'Harbor Lights']);
  expect(card(rendered.container, 12).querySelector('[data-testid="card-poster"]').getAttribute('src')).toBe('/art/bridge.jpg');
  expect(card(rendered.container, 12).querySelector('[data-testid="card-poster-fallback"]')).toBeNull();
  expect(card(rendered.container, 13).querySelector('[data-testid="card-poster"]')).toBeNull();
  expect(card(rendered.container, 13).querySelector('[data-testid="card-poster-initials"]').textContent).toBe('HL');

  expect(texts(rendered.container, 'episode-progress-text')).toEqual(['12 / 18', '8 / 8']);
  const fills = rendered.container.querySelectorAll('[data-testid="episode-progress-fill"]');
  expect(fills[0].getAttribute('style')).toContain('67%');
  expect(fills[1].getAttribute('style')).toContain('100%');
  expect(texts(rendered.container, 'missing-badge')).toEqual(['6 missing']);
  expect(card(rendered.container, 13).querySelector('[data-testid="missing-badge"]')).toBeNull();
  expect(texts(rendered.container, 'show-quality')).toEqual(['HD-1080p', '4K-2160p']);
  globalThis.fetch = realFetch;
});

test('Unmonitor waits for the global dialog and never opens the detail route', async () => {
  setLocation('/monitored');
  await seed();
  const rendered = render(MonitoredPage);
  const dialog = render(ConfirmDialog);
  await settle();

  const unmonitor = card(rendered.container, 12).querySelector('[data-testid="unmonitor-button"]') as HTMLElement;
  flushSync(() => unmonitor.click());
  await settle();

  expect(confirmation()?.id).toBe('unmonitor-12');
  expect(confirmation()?.kind).toBe('danger');
  expect(confirmation()?.message).toBe('Stop monitoring The Bridge?');
  expect(dialog.container.querySelector('[data-testid="confirm-dialog"]')).toBeTruthy();
  expect(texts(dialog.container, 'confirm-message')).toEqual(['Stop monitoring The Bridge?']);
  expect(calls.filter((call) => call.startsWith('DELETE'))).toEqual([]);
  expect(currentPath()).toBe('/monitored');

  flushSync(() => (dialog.container.querySelector('[data-testid="confirm-cancel"]') as HTMLElement).click());
  await settle();
  expect(calls.filter((call) => call.startsWith('DELETE'))).toEqual([]);
  expect(card(rendered.container, 12)).toBeTruthy();
  expect(confirmation()).toBeNull();

  flushSync(() => unmonitor.click());
  await settle();
  flushSync(() => (dialog.container.querySelector('[data-testid="confirm-accept"]') as HTMLElement).click());
  await settle();

  expect(calls.filter((call) => call.startsWith('DELETE'))).toEqual(['DELETE /api/series/12']);
  expect(card(rendered.container, 12)).toBeNull();
  expect(rendered.container.querySelectorAll('[data-testid="monitored-card"]')).toHaveLength(1);
  expect(currentPath()).toBe('/monitored');
  globalThis.fetch = realFetch;
});

test('clicking a card navigates to its TV detail route', async () => {
  setLocation('/monitored');
  await seed();
  const rendered = render(MonitoredPage);
  await settle();

  flushSync(() => card(rendered.container, 13).click());
  expect(currentPath()).toBe('/tv/1404');
  globalThis.fetch = realFetch;
});
