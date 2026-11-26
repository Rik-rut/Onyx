import { expect, test } from 'vitest';
import { render } from '@testing-library/svelte';
import AppShell from '../src/components/AppShell.svelte';
import { paletteKey } from '../src/lib/palette';
import { currentPath, route } from '../src/lib/router.svelte';
import { refresh } from '../src/lib/stores/library.svelte';
import { authSettled } from '../src/lib/stores/auth.svelte';
import { palette, rememberSearch, setPalette } from '../src/lib/stores/ui.svelte';
import { authenticatedFetch } from './auth';

declare const globalThis: {
  fetch: (path: string) => {
    ok: boolean;
    status: number;
    statusText: string;
    text: () => Promise<string>;
  };
};

const realFetch = globalThis.fetch;

// AppShell fetches /api/auth/status on mount; default to an authenticated
// session so these palette tests keep rendering the dashboard.
const defaultFetch = authenticatedFetch(realFetch);
globalThis.fetch = defaultFetch;

function recordFetch(calls: string[]): void {
  globalThis.fetch = authenticatedFetch((path: string) => {
    calls.push(path);
    const body = path.startsWith('/api/library')
      ? {
          movies: [
            { title: 'Heat', imdb_id: 'tt1', year: 2025, path: '/m/heat.mkv', seeding: true },
            { title: 'Dune', imdb_id: 'tt2', year: 2021, path: '/m/dune.mkv', seeding: false },
          ],
          shows: [{ title: 'The Last of Us', tmdb_id: 1403, path: '/tv/lou', seasons: [1], seeding: true }],
          sync: {},
        }
      : { items: [] };
    return { ok: true, status: 200, statusText: 'OK', text: async () => JSON.stringify(body) };
  });
}

function type(word: string): void {
  for (const char of word) paletteKey({ key: char });
}

// The shell renders after the auth status fetch settles (fetch -> text ->
// parse -> state); await the real state signal, not a guessed delay.
const shellReady = () => authSettled();

test('typing filters locally with zero search API calls', async () => {
  const calls: string[] = [];
  recordFetch(calls);
  await refresh();
  rememberSearch('heat');
  setPalette(true, 'he');
  expect(palette().query).toBe('he');
  const rendered = render(AppShell);
  await shellReady();
  expect(rendered.container.querySelector('[data-testid="palette-query"]').textContent).toBe('he');
  expect(calls.filter((path) => path.startsWith('/api/search'))).toEqual([]);
  // Local matches and route shortcuts render without any network round-trip.
  const matches = rendered.container.querySelector('[data-testid="palette-matches"]');
  expect(matches.textContent).toContain('Heat · Movie');
  expect(matches.textContent).toContain('heat');
  // Nav shortcuts only render when they match the typed prefix.
  expect(matches.textContent.includes('Movies')).toBe(false);
  globalThis.fetch = defaultFetch;
});

test('Ctrl+K opens the palette and Enter jumps to /search', async () => {
  paletteKey({ key: 'k', ctrlKey: true });
  expect(palette().open).toBe(true);
  expect(palette().query).toBe('');
  type('dune');
  expect(palette().query).toBe('dune');
  paletteKey({ key: 'Escape' });
  expect(palette()).toEqual({ open: false, query: '' });

  setPalette(true, 'the lake');
  paletteKey({ key: 'Enter' });
  expect(palette()).toEqual({ open: false, query: '' });
  expect(currentPath()).toBe('/search');
  expect(route()?.params.q).toBe('the lake');
});

test('a header click opens the palette', async () => {
  setPalette(false, '');
  const rendered = render(AppShell);
  await shellReady();
  expect(rendered.container.querySelector('[data-testid="palette-closed"]')).toBeTruthy();
  rendered.container.querySelector('[data-testid="palette-trigger"]').click();
  await null;
  expect(palette().open).toBe(true);
  expect(rendered.container.querySelector('[data-testid="command-palette"]')).toBeTruthy();
});

test('slash opens the palette only while idle', async () => {
  setPalette(false, '');
  paletteKey({ key: '/' });
  expect(palette().open).toBe(true);
  // A focused field owns the character: "/" must not hijack typing.
  setPalette(false, '');
  paletteKey({ key: '/', target: {} });
  expect(palette().open).toBe(false);
});
