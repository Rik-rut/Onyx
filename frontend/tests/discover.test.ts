import { expect, test } from 'vitest';
import { render } from '@testing-library/svelte';
import DiscoverPage from '../src/components/DiscoverPage.svelte';
import { currentPath, route, setLocation } from '../src/lib/router.svelte';
import { errorText, lastAttempt, payload, retryNow } from '../src/lib/stores/discover.svelte';

declare const globalThis: {
  fetch: (path: string) => {
    ok: boolean;
    status: number;
    statusText: string;
    text: () => Promise<string>;
  };
};

const realFetch = globalThis.fetch;

const railsBody = {
  spotlight: { title: 'Dune Part Two', year: 2024, imdb_id: 'tt111', poster: '', rating: 8.2, library_status: 'available' },
  trending_movies: [
    { title: 'Heat', year: 2025, imdb_id: 'tt222', poster: '', rating: 7.4, library_status: null },
    { title: 'Sinners', year: 2024, imdb_id: 'tt333', poster: '', rating: 6.9 },
  ],
  trending_tv: [{ title: 'The Last of Us', tmdb_id: 1403, poster: '', rating: 8.6, library_status: 'monitored' }],
  top_rated_movies: [{ title: 'Dune Part Two', year: 2024, imdb_id: 'tt111', poster: '', rating: 8.2, library_status: 'available' }],
  genres: [],
  genres_by_type: {},
};

function serve(calls: string[], failing: boolean): void {
  globalThis.fetch = (path: string) => {
    calls.push(path);
    if (failing) throw new Error('scrape failed');
    return {
      ok: true,
      status: 200,
      statusText: 'OK',
      text: async () => JSON.stringify(railsBody),
    };
  };
}

// Svelte schedules re-runs in microtasks; awaiting lets them settle.
const flush = async () => await null;

test('a failed scrape degrades to a retryable panel, then refills on retry', async () => {
  const calls: string[] = [];
  serve(calls, true);
  setLocation('/', '');
  const rendered = render(DiscoverPage);
  // Awaiting the attempt promise is the real signal; one flush then lets Svelte
  // paint the resulting state.
  await lastAttempt();
  await flush();
  expect(calls).toEqual(['/api/discover']);
  expect(rendered.container.querySelector('[data-testid="discover-error"]')).toBeTruthy();
  expect(rendered.container.querySelector('[data-testid="discover-error-message"]').textContent).toContain(
    'Discover unavailable',
  );

  serve(calls, false);
  await retryNow();
  await flush();
  expect(payload()).toBeTruthy();
  const rails = rendered.container.querySelectorAll('[data-testid="media-rail"]');
  expect(rails.length).toBe(3);
  expect(Array.from(rails).map((rail) => rail.getAttribute('data-rail'))).toEqual([
    'Trending Movies',
    'Trending TV Shows',
    'Top Rated Movies',
  ]);
  expect(rendered.container.querySelector('[data-testid="hero-spotlight"]')).toBeTruthy();

  // Badges: rating + library availability render per card.
  const cards = rendered.container.querySelectorAll('[data-testid="poster-card"]');
  expect(cards.length).toBe(5);
  expect(rendered.container.querySelector('[data-testid="rating-badge"]').textContent).toContain('8.2');
  expect(rendered.container.querySelector('[data-testid="availability-badge"]').getAttribute('data-status')).toBe(
    'available',
  );
  expect(rendered.container.querySelector('[data-testid="availability-badge"]').textContent).toBe('In Library');

  // Clicking any card opens its dedicated detail route.
  rendered.container.querySelector('[data-testid="poster-card"][data-id="tt222"]').click();
  await flush();
  expect(currentPath()).toBe('/movie/tt222');
  expect(route()?.view).toBe('movie');

  rendered.container.querySelector('[data-testid="poster-card"][data-kind="tv"]').click();
  await flush();
  expect(currentPath()).toBe('/tv/1403');
  globalThis.fetch = realFetch;
});
