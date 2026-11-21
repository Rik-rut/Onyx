import { flushSync } from 'svelte';
import { expect, test } from 'vitest';
import { fireEvent, render } from '@testing-library/svelte';
import LibraryPage from '../src/components/LibraryPage.svelte';
import { currentPath, navigate, route } from '../src/lib/router.svelte';
import { formatBytes, libraryBadgeLabel } from '../src/lib/api';
import { answerConfirmation, confirmation } from '../src/lib/stores/ui.svelte';
import { isCached, libraryCount, seededTitles } from '../src/lib/stores/library.svelte';

declare const globalThis: {
  fetch: (path: string, options?: Record<string, unknown>) => {
    ok: boolean;
    status: number;
    statusText: string;
    text: () => Promise<string>;
  };
};

const realFetch = globalThis.fetch;

// Svelte schedules re-runs in microtasks; awaiting lets them settle.
const flush = async () => await null;
const settle = async (done: () => boolean, tries: number = 24) => {
  for (let attempt = 0; attempt < tries; attempt += 1) {
    if (done()) return;
    await flush();
  }
};

const respond = (payload: unknown) => ({
  ok: true,
  status: 200,
  statusText: 'OK',
  text: async () => JSON.stringify(payload),
});

function libraryBody() {
  return {
    movies: [
      {
        name: 'heat.mkv',
        title: 'Heat',
        year: 2025,
        path: '/movies/heat.mkv',
        file_count: 1,
        size_mb: 2_450,
        primary_ext: 'mkv',
        imdb_id: 'tt888',
        seeding: true,
        poster: '',
      },
      {
        // A disk entry without an imdb id has no detail link.
        name: 'disk only special.mkv',
        title: 'Disk Only Special',
        year: null,
        path: '/movies/disk only special.mkv',
        file_count: 2,
        size_mb: 700,
        primary_ext: 'mkv',
        imdb_id: null,
        seeding: false,
        poster: '',
      },
    ],
    shows: [
      {
        name: 'the last of us',
        title: 'The Last of Us',
        year: 2023,
        path: '/tv/the last of us',
        seasons_count: 1,
        episodes_count: 9,
        monitored_count: 9,
        missing: [10, 11],
        monitored: true,
        monitored_id: 5,
        tmdb_id: 1_403,
        seeding: true,
        poster: '',
      },
      {
        name: 'orphan clip',
        title: 'Orphan Clip',
        year: null,
        path: '/tv/orphan clip',
        seasons_count: 0,
        episodes_count: 0,
        monitored_count: 0,
        missing: [],
        monitored: false,
        monitored_id: null,
        tmdb_id: 2_002,
        seeding: false,
        poster: '',
      },
    ],
    sync: {},
  };
}

let calls: string[] = [];
let bodies: Record<string, unknown>[] = [];

globalThis.fetch = (path: string, options?: Record<string, unknown>) => {
  calls.push(path);
  bodies.push(JSON.parse(String(options?.body ?? '{}')) as Record<string, unknown>);
  const [bare] = path.split('?');
  if (bare === '/api/library') return respond(libraryBody());
  if (bare.startsWith('/api/library/')) return respond({ status: 'ok' });
  if (bare === '/api/queue/import') return respond({ status: 'queued' });
  throw new Error(`unmocked path ${bare}`);
};

const rowTitles = (container: HTMLElement): Array<string | null> =>
  Array.from(container.querySelectorAll('[data-testid="library-row"]'))
    .map((row) => row.getAttribute('data-title'));

const findRow = (container: HTMLElement, title: string): HTMLElement =>
  Array.from(container.querySelectorAll('[data-testid="library-row"]'))
    .find((row) => row.getAttribute('data-title') === title) as HTMLElement;

const pill = (container: HTMLElement, label: string): HTMLElement =>
  Array.from(container.querySelectorAll('[data-testid="library-filter-pill"]'))
    .find((button) => button.textContent?.trim() === label) as HTMLElement;

test('filter pills and the sort selector reshape the cached rows', async () => {
  navigate('/library');
  calls = [];
  const rendered = render(LibraryPage);
  await settle(() => isCached() && libraryCount() === 4, 24);
  await flush();
  const container = rendered.container;

  // The first visit scans exactly once; the guard ignores cache re-runs.
  for (let attempt = 0; attempt < 3; attempt += 1) await flush();
  expect(calls.filter((path) => path === '/api/library')).toEqual(['/api/library']);
  expect(container.querySelector('[data-testid="library-count"]').textContent).toBe('4 titles');
  expect(container.querySelector('[data-testid="library-seeded"]').textContent).toBe('2 seeded');

  expect(Array.from(container.querySelectorAll('[data-testid="library-filter-pill"]'))
    .map((button) => button.textContent.trim())).toEqual(['All', 'Movies', 'TV Shows', 'Seeding']);
  expect(Array.from(container.querySelectorAll('[data-testid="library-sort"] option'))
    .map((option) => option.textContent.trim())).toEqual(['Title', 'Year', 'Size']);
  expect(rowTitles(container)).toEqual(['Disk Only Special', 'Heat', 'Orphan Clip', 'The Last of Us']);

  // Cells and badges still report disk and tracker facts.
  const heat = findRow(container, 'Heat');
  expect(heat.getAttribute('data-kind')).toBe('movie');
  expect(heat.getAttribute('data-seeded')).toBe('true');
  expect(heat.querySelector('[data-testid="library-detail"]').textContent).toBe(
    `1 files · ${formatBytes(2_450 * 1_000_000)}`,
  );
  expect(heat.querySelector('[data-testid="library-badge"]').textContent).toBe(libraryBadgeLabel('available'));
  expect(findRow(container, 'The Last of Us').querySelector('[data-testid="library-badge"]').textContent)
    .toBe(libraryBadgeLabel('monitored'));
  expect(Array.from(container.querySelectorAll('[data-testid="library-link"]'))
    .map((link) => link.getAttribute('href'))).toEqual(['/movie/tt888', '/tv/2002', '/tv/1403']);
  expect(container.querySelectorAll('[data-testid="library-no-action"]').length).toBe(1);

  // Category + state pills filter the same list.
  pill(container, 'Movies').click();
  flushSync();
  expect(container.querySelector('[data-testid="library-tabs"]').getAttribute('data-active')).toBe('movies');
  expect(rowTitles(container)).toEqual(['Disk Only Special', 'Heat']);
  pill(container, 'TV Shows').click();
  flushSync();
  expect(rowTitles(container)).toEqual(['Orphan Clip', 'The Last of Us']);
  pill(container, 'Seeding').click();
  flushSync();
  expect(rowTitles(container)).toEqual(['Heat', 'The Last of Us']);
  pill(container, 'All').click();
  flushSync();
  expect(rowTitles(container).length).toBe(4);

  // Year sorts newest-first; size sorts largest-first; both break ties by title.
  const sort = container.querySelector('[data-testid="library-sort"]') as HTMLSelectElement;
  fireEvent.change(sort, { target: { value: 'year' } });
  flushSync();
  expect(rowTitles(container)).toEqual(['Heat', 'The Last of Us', 'Disk Only Special', 'Orphan Clip']);
  fireEvent.change(sort, { target: { value: 'size' } });
  flushSync();
  expect(rowTitles(container)).toEqual(['Heat', 'Disk Only Special', 'Orphan Clip', 'The Last of Us']);
  fireEvent.change(sort, { target: { value: 'title' } });
  flushSync();
  expect(rowTitles(container)).toEqual(['Disk Only Special', 'Heat', 'Orphan Clip', 'The Last of Us']);
});

test('Rescan Library re-runs the disk scan rather than the queue import', async () => {
  navigate('/library');
  calls = [];
  const rendered = render(LibraryPage);
  await settle(() => isCached() && calls.includes('/api/library'), 24);
  const before = calls.filter((path) => path === '/api/library').length;

  rendered.container.querySelector('[data-testid="rescan-library"]').click();
  await settle(() => calls.filter((path) => path === '/api/library').length > before, 24);
  await flush();
  expect(calls.filter((path) => path === '/api/library').length).toBe(before + 1);
  expect(calls).not.toContain('/api/queue/import');
  expect(rendered.container.querySelector('[data-testid="library-count"]').textContent).toBe('4 titles');
});

test('card clicks navigate while action buttons stay isolated and delete is confirmed', async () => {
  navigate('/library');
  calls = [];
  bodies = [];
  const rendered = render(LibraryPage);
  await settle(() => isCached() && libraryCount() === 4, 24);
  await flush();
  const container = rendered.container;

  // The whole card is the detail-route target when the disk row carries an id.
  findRow(container, 'Heat').click();
  flushSync();
  expect(currentPath()).toBe('/movie/tt888');
  navigate('/library');
  flushSync();
  findRow(container, 'The Last of Us').click();
  flushSync();
  expect(currentPath()).toBe('/tv/1403');
  navigate('/library');
  flushSync();

  // Stop seeding posts remove-seed with the on-disk name and never navigates.
  findRow(container, 'Heat').querySelector('[data-testid="stop-seeding"]').click();
  flushSync();
  await settle(() => calls.includes('/api/library/remove-seed'), 24);
  expect(currentPath()).toBe('/library');
  expect(bodies[calls.indexOf('/api/library/remove-seed')]).toEqual({
    kind: 'movie',
    name: 'heat.mkv',
    confirm: false,
  });

  // Track and Untrack both stop propagation; the label reflects stored state.
  const monitored = findRow(container, 'The Last of Us').querySelector('[data-testid="track-toggle"]');
  expect(monitored.textContent).toBe('Untrack');
  monitored.click();
  flushSync();
  await settle(() => calls.includes('/api/library/untrack'), 24);
  expect(currentPath()).toBe('/library');
  expect(bodies[calls.indexOf('/api/library/untrack')]).toEqual({
    kind: 'tv',
    name: 'the last of us',
    confirm: false,
  });

  const unmonitored = findRow(container, 'Orphan Clip').querySelector('[data-testid="track-toggle"]');
  expect(unmonitored.textContent).toBe('Track');
  unmonitored.click();
  flushSync();
  await settle(() => calls.includes('/api/library/track'), 24);
  expect(currentPath()).toBe('/library');
  expect(bodies[calls.indexOf('/api/library/track')]).toEqual({
    kind: 'tv',
    name: 'orphan clip',
    confirm: false,
  });

  // Delete waits for the global confirmation before sending confirm: true.
  const deletes = () => calls.filter((path) => path === '/api/library/delete').length;
  const beforeDelete = deletes();
  findRow(container, 'Heat').querySelector('[data-testid="delete-library"]').click();
  flushSync();
  expect(confirmation()?.kind).toBe('danger');
  expect(confirmation()?.message).toContain('Heat');
  expect(currentPath()).toBe('/library');
  expect(deletes()).toBe(beforeDelete);
  answerConfirmation(true);
  await settle(() => deletes() === beforeDelete + 1, 24);
  expect(bodies[calls.indexOf('/api/library/delete')]).toEqual({
    kind: 'movie',
    name: 'heat.mkv',
    confirm: true,
  });
  expect(currentPath()).toBe('/library');

  findRow(container, 'The Last of Us').querySelector('[data-testid="delete-library"]').click();
  flushSync();
  answerConfirmation(false);
  await flush();
  expect(deletes()).toBe(beforeDelete + 1);
  expect(confirmation()).toBeNull();
  expect(currentPath()).toBe('/library');
});

test('the search box filters the library grid locally without extra backend calls', async () => {
  navigate('/library?q=heat');
  calls = [];
  const rendered = render(LibraryPage);
  await settle(() => isCached() && libraryCount() === 4, 24);
  await flush();
  const container = rendered.container;
  const input = container.querySelector('[data-testid="library-search-input"]') as HTMLInputElement;

  expect(input.value).toBe('heat');
  expect(rowTitles(container)).toEqual(['Heat']);
  expect(findRow(container, 'Heat').querySelector('[data-testid="library-link"]').getAttribute('href')).toBe('/movie/tt888');
  expect(calls.filter((path) => path === '/api/library').length).toBe(1);

  fireEvent.input(input, { target: { value: 'orphan' } });
  flushSync();
  await flush();
  expect(route()?.params?.q).toBe('orphan');
  expect(rowTitles(container)).toEqual(['Orphan Clip']);
  expect(findRow(container, 'Orphan Clip').querySelector('[data-testid="library-link"]').getAttribute('href')).toBe('/tv/2002');

  fireEvent.input(input, { target: { value: '' } });
  flushSync();
  expect(rowTitles(container).length).toBe(4);

  // Unmatched disk entries still match as plain, non-linked cards.
  navigate('/library?q=special');
  await flush();
  expect(rowTitles(container)).toEqual(['Disk Only Special']);
  expect(findRow(container, 'Disk Only Special').querySelector('[data-testid="library-title-plain"]').textContent).toBe('Disk Only Special');
  expect(findRow(container, 'Disk Only Special').querySelector('[data-testid="library-link"]')).toBeNull();

  navigate('/library');
  globalThis.fetch = realFetch;
});
