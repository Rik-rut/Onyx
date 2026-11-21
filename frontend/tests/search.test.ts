import { expect, test } from 'vitest';
import { render } from '@testing-library/svelte';
import SearchPage from '../src/components/SearchPage.svelte';
import { route, setLocation } from '../src/lib/router.svelte';
import {
  errors,
  lastAttempt,
  movies,
  perform,
  retry,
  retryMovies,
  retryTv,
  tv,
} from '../src/lib/stores/search.svelte';
import { findShow, invalidate, refresh } from '../src/lib/stores/library.svelte';
import { recentSearches } from '../src/lib/stores/ui.svelte';

declare const globalThis: {
  fetch: (path: string) => {
    ok: boolean;
    status: number;
    statusText: string;
    text: () => Promise<string>;
  };
};

const realFetch = globalThis.fetch;

const movieResults = [
  { title: 'Dune Part Two', year: 2024, imdb_id: 'tt111', poster: '', rating: 8.2 },
  { title: 'Dune', year: 1984, imdb_id: 'tt444', poster: '', rating: 5.9 },
];
const tvResults = [{ title: 'Dune: Prophecy', tmdb_id: 4455, poster: '', rating: 7.1 }];
const libraryPayload = {
  movies: [
    {
      name: 'Dune.Part.Two.2024',
      title: 'Dune Part Two',
      year: 2024,
      path: '/library/movies/dune',
      file_count: 1,
      size_mb: 2200,
      primary_ext: 'mkv',
      imdb_id: 'tt111',
      seeding: true,
      poster: '',
    },
  ],
  shows: [
    {
      name: 'Dune.Prophecy',
      title: 'Dune: Prophecy',
      year: 2024,
      path: '/library/tv/dune-prophecy',
      seasons_count: 1,
      episodes_count: 5,
      monitored_count: 5,
      missing: [],
      monitored: true,
      monitored_id: 12,
      tmdb_id: 4455,
      seeding: false,
      poster: '',
    },
  ],
  sync: {},
};

let tvDown = false;

function serve(calls: string[]): void {
  globalThis.fetch = (path: string) => {
    const parts = path.split('?');
    const bare = parts[0];
    const queryPart = parts.length > 1 ? parts[1] : '';
    calls.push(path);
    const respond = (body: unknown) => ({
      ok: true,
      status: 200,
      statusText: 'OK',
      text: async () => JSON.stringify(body),
    });
    if (bare === '/api/search/tv' && tvDown) {
      return {
        ok: false,
        status: 502,
        statusText: 'Bad Gateway',
        text: async () => JSON.stringify({ detail: 'tv indexer timed out' }),
      };
    }
    if (bare === '/api/search/movies') return respond(queryPart.includes('zzzz') ? [] : movieResults);
    if (bare === '/api/search/tv') return respond(queryPart.includes('zzzz') ? [] : tvResults);
    if (bare === '/api/library') return respond(libraryPayload);
    throw new Error(`unmocked ${bare}`);
  };
}

const searchCalls = (calls: string[]) => calls.filter((path) => path.startsWith('/api/search/'));

// Svelte schedules re-runs in microtasks; awaiting lets them settle.
const flush = async () => await null;

test('parallel sources fill tabs, badges, and availability pills', async () => {
  const calls: string[] = [];
  tvDown = false;
  serve(calls);
  invalidate();
  await refresh();
  setLocation('/search', 'q=dune');
  const rendered = render(SearchPage);
  expect(route()?.view).toBe('search');
  expect(route()?.params.q).toBe('dune');
  // Both sources issued before either response resolved: parallel, one each.
  expect(searchCalls(calls)).toEqual(['/api/search/movies?q=dune', '/api/search/tv?q=dune']);
  await lastAttempt();
  await flush();

  expect(movies()).toHaveLength(2);
  expect(tv()).toHaveLength(1);
  expect(errors()).toEqual({ movies: null, tv: null });
  expect(recentSearches()).toContain('dune');

  expect(rendered.container.querySelector('[data-testid="badge-movies"]').getAttribute('data-count')).toBe(
    '2',
  );
  expect(rendered.container.querySelector('[data-testid="badge-tv"]').getAttribute('data-count')).toBe('1');

  const cards = rendered.container.querySelectorAll('[data-testid="poster-card"]');
  expect(cards.length).toBe(3);
  expect(Array.from(cards).map((card) => card.getAttribute('data-kind'))).toEqual(['movie', 'movie', 'tv']);

  // Availability pills render only for ids the disk library actually seeds.
  const pills = rendered.container.querySelectorAll('[data-testid="availability-pill"]');
  expect(Array.from(pills).map((pill) => pill.getAttribute('data-id'))).toEqual(['tt111', '4455']);
  expect(findShow(4455)).toBeTruthy();

  // Tab buttons filter rows while the per-type badges stay put.
  rendered.container.querySelector('[data-testid="tab-movies"]').click();
  await flush();
  expect(rendered.container.querySelector('[data-testid="rows-tv"]')).toBeNull();
  expect(rendered.container.querySelectorAll('[data-testid="poster-card"]').length).toBe(2);

  rendered.container.querySelector('[data-testid="tab-tv"]').click();
  await flush();
  expect(rendered.container.querySelector('[data-testid="rows-movies"]')).toBeNull();
  expect(rendered.container.querySelectorAll('[data-testid="poster-card"]').length).toBe(1);

  rendered.container.querySelector('[data-testid="tab-all"]').click();
  await flush();
  expect(rendered.container.querySelectorAll('[data-testid="poster-card"]').length).toBe(3);
  globalThis.fetch = realFetch;
});

test('a dead tv indexer degrades to a retry panel; retry re-requests only tv', async () => {
  const calls: string[] = [];
  tvDown = true;
  serve(calls);
  invalidate();
  await refresh();
  // Distinct query: the store dedupes a re-perform of the same attempted one.
  setLocation('/search', 'q=heat');
  const rendered = render(SearchPage);
  expect(searchCalls(calls)).toEqual(['/api/search/movies?q=heat', '/api/search/tv?q=heat']);
  await lastAttempt();
  await flush();

  expect(errors()).toEqual({ movies: null, tv: 'tv indexer timed out (HTTP 502)' });
  expect(movies()).toHaveLength(2);
  expect(tv()).toEqual([]);

  expect(rendered.container.querySelector('[data-testid="error-tv"]')).toBeTruthy();
  expect(rendered.container.querySelector('[data-testid="error-tv-message"]').textContent).toContain(
    'tv indexer timed out',
  );
  expect(rendered.container.querySelector('[data-testid="error-movies"]')).toBeNull();
  // The surviving source still renders its rows next to the panel.
  expect(rendered.container.querySelectorAll('[data-testid="poster-card"][data-kind="movie"]').length).toBe(
    2,
  );
  // Only the failed source gets a retry affordance.
  expect(rendered.container.querySelector('[data-testid="retry-tv"]')).toBeTruthy();
  expect(rendered.container.querySelector('[data-testid="retry-movies"]')).toBeNull();

  tvDown = false;
  const beforeRetry = calls.length;
  rendered.container.querySelector('[data-testid="retry-tv"]').click();
  expect(searchCalls(calls.slice(beforeRetry))).toEqual(['/api/search/tv?q=heat']);
  await lastAttempt();
  await flush();
  expect(errors().tv).toBeNull();
  expect(tv()).toHaveLength(1);
  expect(rendered.container.querySelectorAll('[data-testid="poster-card"]').length).toBe(3);
  globalThis.fetch = realFetch;
});

test('retry() re-requests only failed sources', async () => {
  const calls: string[] = [];
  tvDown = true;
  serve(calls);
  setLocation('/search', 'q=dune');
  const rendered = render(SearchPage);
  await lastAttempt();
  await flush();
  expect(errors().tv).toContain('tv indexer timed out');

  tvDown = false;
  const beforeRetry = calls.length;
  await retry();
  expect(searchCalls(calls.slice(beforeRetry))).toEqual(['/api/search/tv?q=dune']);
  await flush();
  expect(errors()).toEqual({ movies: null, tv: null });
  expect(tv()).toHaveLength(1);
  globalThis.fetch = realFetch;
});

test('a query nothing matches renders the No results panel', async () => {
  const calls: string[] = [];
  tvDown = false;
  serve(calls);
  setLocation('/search', 'q=zzzz');
  const rendered = render(SearchPage);
  expect(searchCalls(calls)).toEqual(['/api/search/movies?q=zzzz', '/api/search/tv?q=zzzz']);
  await lastAttempt();
  await flush();

  expect(movies()).toEqual([]);
  expect(tv()).toEqual([]);
  expect(errors()).toEqual({ movies: null, tv: null });
  expect(rendered.container.querySelector('[data-testid="poster-card"]')).toBeNull();
  const empty = rendered.container.querySelector('[data-testid="search-empty"]');
  expect(empty).toBeTruthy();
  expect(rendered.container.querySelector('[data-testid="search-empty-message"]').textContent).toContain(
    'zzzz',
  );
  globalThis.fetch = realFetch;
});
