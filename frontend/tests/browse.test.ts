import { expect, test } from 'vitest';
import { render } from '@testing-library/svelte';
import BrowsePage from '../src/components/BrowsePage.svelte';
import { currentPath, route, setLocation } from '../src/lib/router.svelte';
import { lastLoad, visible } from '../src/lib/stores/browse.svelte';
import type { MediaItem } from '../src/lib/api';

declare const globalThis: {
  fetch: (path: string) => {
    ok: boolean;
    status: number;
    statusText: string;
    text: () => Promise<string>;
  };
};

const realFetch = globalThis.fetch;

const movieItems: MediaItem[] = [];
for (let index = 1; index <= 20; index += 1) {
  movieItems.push({
    imdb_id: `tt${String(index).padStart(3, '0')}`,
    title: `Movie ${index}`,
    year: 2000 + index,
    poster: '',
    rating: 6 + (index % 4),
    genres: index % 3 === 0 ? ['Comedy', 'Drama'] : index % 3 === 2 ? ['Action', 'Drama'] : ['Drama'],
    library_status: index % 5 === 0 ? 'monitored' : index % 5 === 2 ? 'available' : null,
  });
}

const tvItems: MediaItem[] = [];
for (let index = 1; index <= 12; index += 1) {
  tvItems.push({
    tmdb_id: 900 + index,
    title: `Show ${index}`,
    year: 2000 + index,
    poster: '',
    rating: 7,
    genres: ['Drama', 'Sci-Fi'],
    library_status: index % 3 === 0 ? 'queued' : null,
  });
}

const browseCalls: string[] = [];

// The mock backend filters server-side: /api/discover/browse answers with the
// requested page of the filtered pool, 4 rows per page.
globalThis.fetch = (path: string) => {
  browseCalls.push(path);
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    text: async () => {
      const query = new URLSearchParams(path.slice(path.indexOf('?') + 1));
      const pool = query.get('media_type') === 'tv' ? tvItems : movieItems;
      const genre = query.get('genre') ?? '';
      const filtered = genre === ''
        ? pool
        : pool.filter((item) => item.genres?.includes(genre) ?? false);
      const page = Number(query.get('page') ?? '1');
      const items = filtered.slice((page - 1) * 4, page * 4);
      return JSON.stringify({ page, page_size: 4, total: filtered.length, items });
    },
  };
};

const flush = async () => await null;

// A filter switch re-runs the load effect one microtask after the click, so
// one `await lastLoad()` may capture the previous request: re-read the store
// signal after each flush until the new page has landed.
const waitForLoad = async (): Promise<void> => {
  for (let round = 0; round < 4; round += 1) {
    await lastLoad();
    await flush();
  }
};

const countCalls = (matcher: (call: string) => boolean): number =>
  browseCalls.filter(matcher).length;

const unfilteredPageOne = (call: string): boolean =>
  call.includes('/api/discover/browse') && call.includes('page=1') && !call.includes('genre=');

test('browse renders page 1, endless-scrolls into page 2, and re-filters on chip clicks', async () => {
  setLocation('/movies', '');
  const page = render(BrowsePage);
  await waitForLoad();

  expect(currentPath()).toBe('/movies');
  expect(route()?.view).toBe('movies');
  expect(page.container.querySelector('[data-testid="browse-page"]')).toBeTruthy();
  const cards = page.container.querySelectorAll('[data-testid="poster-card"]');
  expect(cards.length).toBeGreaterThanOrEqual(4);
  expect(cards[0]?.getAttribute('data-id')).toBe('tt001');
  const grid = page.container.querySelector('[data-testid="browse-grid"]');
  expect(grid).toBeTruthy();
  expect(grid?.className).toContain('grid-cols-2');
  // Page 1 fetched exactly once: re-running the load effect never refetches.
  expect(countCalls(unfilteredPageOne)).toBe(1);

  // The visibility hook (MutationObserver fallback in jsdom) keeps firing as
  // appended rows mutate the grid, so page 2 lands without any click.
  for (let round = 0; round < 8; round += 1) await flush();
  expect(countCalls((call) => call.includes('media_type=movie') && call.includes('page=2') && !call.includes('genre='))).toBeGreaterThanOrEqual(1);
  expect(visible().length).toBeGreaterThan(4);

  const actionChips = page.container.querySelectorAll('[data-testid="browse-genre-chip"][data-genre="Action"]');
  expect(actionChips).toHaveLength(1);
  actionChips[0]?.click();
  await waitForLoad();

  // The grid was reset and page 1 refetched for the genre: rows start at the
  // Action pool (tt002..tt020), never the old unfiltered rows.
  expect(route()?.params?.genre).toBe('Action');
  const actionCards = page.container.querySelectorAll('[data-testid="poster-card"]');
  expect(actionCards.length).toBeGreaterThanOrEqual(4);
  expect(actionCards[0]?.getAttribute('data-id')).toBe('tt002');
  expect(countCalls((call) => call.includes('genre=Action') && call.includes('page=1'))).toBe(1);

  for (let round = 0; round < 8; round += 1) await flush();
  // Seven Action rows exist: exactly one page 2 (short page stops the cascade).
  expect(countCalls((call) => call.includes('genre=Action') && call.includes('page=2'))).toBe(1);
  expect(visible().length).toBeGreaterThanOrEqual(7);

  page.container.querySelector('[data-testid="browse-clear-filter"]')?.click();
  await waitForLoad();
  expect(route()?.params?.genre ?? '').toBe('');
  const clearCards = page.container.querySelectorAll('[data-testid="poster-card"]');
  expect(clearCards.length).toBeGreaterThanOrEqual(4);
  expect(clearCards[0]?.getAttribute('data-id')).toBe('tt001');
  // The clear-filter call carries no genre param at all.
  expect(countCalls(unfilteredPageOne)).toBe(2);

  for (let round = 0; round < 6; round += 1) await flush();
  expect(visible().length).toBeGreaterThanOrEqual(8);
  // Old-genre fetches that were still in flight never splice into the grid.
  expect(visible().length).toBeLessThanOrEqual(20);
});

test('the /tv route renders its own grid with TV chips', async () => {
  setLocation('/tv', '');
  const page = render(BrowsePage);
  await waitForLoad();

  expect(route()?.view).toBe('tv');
  expect(page.container.querySelector('[data-testid="browse-page"]')?.getAttribute('data-view')).toBe('tv');
  const tvCards = page.container.querySelectorAll('[data-testid="poster-card"][data-kind="tv"]');
  expect(tvCards.length).toBeGreaterThanOrEqual(4);
  expect(tvCards[0]?.getAttribute('data-id')).toBe('901');
  expect(page.container.querySelector('[data-testid="browse-genre-chip"]')?.getAttribute('data-genre')).toBe('Drama');
  expect(countCalls((call) => call.includes('media_type=tv') && call.includes('page=1') && !call.includes('genre='))).toBe(1);

  page.container.querySelector('[data-testid="browse-genre-chip"][data-genre="Drama"]')?.click();
  await waitForLoad();
  expect(route()?.params?.genre).toBe('Drama');
  expect(countCalls((call) => call.includes('media_type=tv') && call.includes('genre=Drama') && call.includes('page=1'))).toBe(1);
});

test('an empty genre page shows the No results panel and loads no further pages', async () => {
  setLocation('/tv', '?genre=Noir');
  const page = render(BrowsePage);
  await waitForLoad();

  expect(route()?.params?.genre).toBe('Noir');
  expect(page.container.querySelector('[data-testid="browse-no-results"]')).toBeTruthy();
  expect(page.container.querySelector('[data-testid="browse-no-results-text"]')?.textContent).toContain('No results');
  expect(page.container.querySelectorAll('[data-testid="poster-card"]')).toHaveLength(0);
  // Zero rows means nothing to scroll into view: exactly one request.
  expect(countCalls((call) => call.includes('genre=Noir'))).toBe(1);

  globalThis.fetch = realFetch;
});
