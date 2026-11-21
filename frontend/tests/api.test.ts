import { expect, test } from 'vitest';

declare const globalThis: {
  fetch: (path: string, options?: Record<string, unknown>) => {
    ok: boolean;
    status: number;
    statusText: string;
    text: () => Promise<string>;
  };
};

import { api, ApiError, BADGE_LABELS, bestRelease, filterReleases, formatBytes, formatEta, formatSpeed, isDuplicateDownload, libraryBadgeLabel, releaseResolutionChip, sortReleases } from '../src/lib/api';

const realFetch = globalThis.fetch;

type Served = { status: number; body?: unknown; text?: string };

function installMock(routes: Record<string, Served>, calls: string[]): void {
  const mock = (path: string) => {
    const [bare] = path.split('?');
    const served = routes[bare];
    if (!served) throw new Error(`unmocked path ${bare}`);
    calls.push(path);
    const payload = served.text ?? (served.body === undefined ? '' : JSON.stringify(served.body));
    return {
      ok: served.status < 400,
      status: served.status,
      statusText: served.status === 500 ? 'Internal Server Error' : 'OK',
      text: async () => payload,
    };
  };
  globalThis.fetch = mock as typeof globalThis.fetch;
}

function restore(): void {
  globalThis.fetch = realFetch;
}

test('discovery payloads are typed', async () => {
  const calls: string[] = [];
  installMock(
    {
      '/api/discover': {
        status: 200,
        body: {
          trending_movies: [{ title: 'Heat', year: 2025, imdb_id: 'tt1', poster_url: null, rating: 7.1, library_status: 'available' }],
          trending_tv: [],
          top_rated_movies: [],
        },
      },
    },
    calls,
  );
  const payload = await api.discover();
  expect(payload.trending_movies[0].imdb_id).toBe('tt1');
  expect(payload.trending_movies[0].library_status).toBe('available');
  expect(libraryBadgeLabel(payload.trending_movies[0].library_status)).toBe(BADGE_LABELS.available);
  expect(libraryBadgeLabel('unexpected')).toBe(null);
  expect(calls).toEqual(['/api/discover']);
  restore();
});

test('browse pagination rides the media_type/genre/page params', async () => {
  const calls: string[] = [];
  installMock({ '/api/discover/browse': { status: 200, body: { items: [], total: 0, has_more: true } } }, calls);
  await api.browse('tv', 'Drama', 3);
  expect(calls).toEqual(['/api/discover/browse?media_type=tv&genre=Drama&page=3']);
  restore();
});

test('409 duplicate surfaces as a typed duplicate', async () => {
  const calls: string[] = [];
  installMock({ '/api/queue/download/release': { status: 409, body: { detail: 'Heat already queued' } } }, calls);
  const duplicate = { title: 'Heat 2025 1080p WEB', seeders: 40, score: 5, size_bytes: 1000 };
  try {
    await api.downloadRelease(duplicate, {}, false);
  } catch (failure) {
    expect(isDuplicateDownload(failure)).toBe(true);
    expect(failure).toBeInstanceOf(ApiError);
    const typed = failure as ApiError;
    expect(typed.status).toBe(409);
    expect(typed.detail).toBe('Heat already queued');
    expect(typed.path).toBe('/api/queue/download/release');
  }
  restore();
});

test('500 keeps the HTTP status and falls back to statusText', async () => {
  const calls: string[] = [];
  installMock({ '/api/library/delete': { status: 500, text: 'not json' } }, calls);
  try {
    await api.libraryAction('delete', 'movie', 'Heat');
    expect(false).toBe(true);
  } catch (failure) {
    const typed = failure as ApiError;
    expect(typed.status).toBe(500);
    expect(typed.detail).toBe('Internal Server Error');
  }
  restore();
});

test('a failed connection reports an unreachable backend', async () => {
  const calls: string[] = [];
  installMock({}, calls);
  try {
    await api.queue();
    expect(false).toBe(true);
  } catch (failure) {
    const typed = failure as ApiError;
    expect(typed.status).toBe(0);
    expect(typed.detail).toContain('backend unreachable');
  }
  restore();
});

test('formatters and release ranking', () => {
  expect(formatBytes(0)).toBe('0 B');
  expect(formatBytes(1536)).toBe('1.5 KB');
  expect(formatBytes(2_500_000)).toBe('2.5 MB');
  expect(formatSpeed(1536)).toBe('1.5 KB/s');
  expect(formatEta(3725)).toBe('1h 02m');
  expect(formatEta(75)).toBe('1m 15s');
  expect(formatEta(-1)).toBe('—');

  const items = [
    { title: 'Show S01E01 1080p WEB x264', seeds: 10, score: 3, size_bytes: 500, resolution: '1080p' },
    { title: 'Show S01E01 720p WEB x264', seeds: 90, score: 3, size_bytes: 900, resolution: '720p' },
    { title: 'Show S01E01 4K WEB x265', seeds: 4, score: 9, size_bytes: 100, resolution: '2160p' },
  ];
  expect(releaseResolutionChip(items[0])).toBe('1080p');
  expect(filterReleases(items, '720p').length).toBe(1);
  expect(filterReleases(items, 'All').length).toBe(3);
  expect(sortReleases(items, 'score').map((item) => item.score)).toEqual([9, 3, 3]);
  expect(sortReleases(items, 'seeds').map((item) => item.seeds)).toEqual([90, 10, 4]);
  expect(sortReleases(items, 'size').map((item) => item.size_bytes)).toEqual([100, 500, 900]);
  expect(bestRelease(items).title).toContain('4K');
});
