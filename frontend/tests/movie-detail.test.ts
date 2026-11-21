import { expect, test } from 'vitest';
import { render } from '@testing-library/svelte';
import MovieDetailPage from '../src/components/MovieDetailPage.svelte';
import { api, bestRelease, filterReleases, formatBytes, sortReleases } from '../src/lib/api';
import type { MovieDetails, ReleaseItem } from '../src/lib/api';
import { currentPath, route, setLocation } from '../src/lib/router.svelte';
import { refresh } from '../src/lib/stores/library.svelte';
import { answerConfirmation, clearToasts, closeDrawer, confirmation, drawer, toasts } from '../src/lib/stores/ui.svelte';

declare const globalThis: {
  fetch: (path: string, options?: Record<string, unknown>) => {
    ok: boolean;
    status: number;
    statusText: string;
    text: () => Promise<string>;
  };
  window: Window & typeof globalThis;
};

const realFetch = globalThis.fetch;

const detailBody = (
  imdbId: string,
  title: string,
  degraded: boolean,
  related: Array<{ imdb_id: string; title: string; rating: number; poster: string; year: number }>,
): MovieDetails => ({
  id: `1${imdbId}`,
  imdb_id: imdbId,
  title,
  year: 2049,
  overview: 'A replica drifts through a rain-slick arcology.',
  rating: 8.1,
  genres: ['Sci-Fi', 'Neo-noir'],
  runtime: 117,
  poster: `https://posters/${imdbId}.jpg`,
  stars: ['Aya Moreau', 'Sean Kovel'],
  similar: related,
  degraded,
  in_library: true,
  library_status: 'available',
});

const mockReleases: ReleaseItem[] = [
  {
    indexer: 'Indexer A', title: 'Blade.Runner.2049.2160p.WEB.h264-GRP', infohash: 'a1',
    magnet: 'magnet:?xt=urn:btih:a1', seeds: 9, peers: 1, size_bytes: 78_000_000_000,
    resolution: '2160p', codec: 'h264', source: 'web', score: 15, is_pack: false,
  },
  {
    indexer: 'Indexer B', title: 'Blade.Runner.2049.1080p.BluRay.x264-GRP', infohash: 'a2',
    magnet: 'magnet:?xt=urn:btih:a2', seeds: 6, peers: 3, size_bytes: 8_600_000_000,
    resolution: '1080p', codec: 'x264', source: 'bluray', score: 40, is_pack: false,
  },
  {
    indexer: 'Indexer C', title: 'Blade.Runner.2049.1080p.WEB-DL.x265-GRP', infohash: 'a3',
    magnet: 'magnet:?xt=urn:btih:a3', seeds: 12, peers: 2, size_bytes: 6_400_000_000,
    resolution: '1080p', codec: 'x265', source: 'web', score: 25, is_pack: false,
  },
  {
    indexer: 'Indexer D', title: 'Blade.Runner.2049.720p.HDTV.x264-GRP', infohash: 'a4',
    magnet: 'magnet:?xt=urn:btih:a4', seeds: 2, peers: 8, size_bytes: 4_300_000_000,
    resolution: '720p', codec: 'x264', source: 'hdtv', score: 60, is_pack: false,
  },
];

const dupeRelease: ReleaseItem = {
  indexer: 'Indexer E',
  title: 'Dup.Movie.2024.1080p.WEB.h264-GRP',
  infohash: 'b1',
  magnet: 'magnet:?xt=urn:btih:b1',
  seeds: 5,
  peers: 1,
  size_bytes: 5_000_000_000,
  resolution: '1080p',
  codec: 'h264',
  source: 'web',
  score: 30,
  is_pack: false,
};

// Records POSTed bodies for /api/queue/download/release. With duplicate=true
// the first (force:false) call answers 409 duplicate and the force resubmit
// answers 200; otherwise every download succeeds.
function installFetch(routes: Record<string, unknown>, downloadCalls: DownloadCall[], duplicate = false): void {
  globalThis.fetch = (path: string, options?: Record<string, unknown>) => {
    const [bare] = path.split('?');
    if (bare === '/api/queue/download/release') {
      const body = JSON.parse(String(options?.body ?? '{}'));
      downloadCalls.push({ force: body.force === true, title: String(body.title ?? '') });
      if (!duplicate && body.force !== true) {
        return { ok: true, status: 200, statusText: 'OK', text: async () => JSON.stringify({ success: true }) };
      }
      if (body.force === true) {
        return { ok: true, status: 200, statusText: 'OK', text: async () => JSON.stringify({ success: true }) };
      }
      return {
        ok: false,
        status: 409,
        statusText: 'Conflict',
        text: async () => JSON.stringify({ success: false, duplicate: true, existing: { path: '/movies/dup' } }),
      };
    }
    if (bare in routes) {
      const payload = routes[bare];
      return { ok: true, status: 200, statusText: 'OK', text: async () => JSON.stringify(payload) };
    }
    throw new Error(`unmocked path ${bare}`);
  };
}

interface DownloadCall {
  force: boolean;
  title: string;
}

const restore = (): void => {
  globalThis.fetch = realFetch;
};

const flush = async (): Promise<void> => {
  await null;
};

// Svelte + the mocked fetch settle over microtasks; spin until settled.
const waitFor = async (predicate: () => boolean): Promise<void> => {
  for (let attempt = 0; attempt < 200 && !predicate(); attempt += 1) await flush();
  if (!predicate()) throw new Error('state never settled');
};

test('detail page renders metadata/degraded details and retries a failed fetch', async () => {
  installFetch({
    '/api/movie/tt555/details': detailBody(
      'tt555',
      'Blade Runner 2049',
      true,
      [{ imdb_id: 'tt666', title: 'Heat Replica', rating: 7.4, poster: '', year: 2052 }],
    ),
    '/api/movie/tt666/details': detailBody('tt666', 'Heat Replica', false, []),
    '/api/library': {
      movies: [
        {
          name: 'blade.runner.2049', title: 'Blade Runner 2049', year: 2049,
          path: '/movies/blade.runner.2049', file_count: 1, size_mb: 4200,
          primary_ext: 'mkv', imdb_id: 'tt555', seeding: false, poster: '',
        },
      ],
      shows: [],
      sync: {},
    },
  }, []);
  await refresh();
  setLocation('/movie/tt555', '');
  const rendered = render(MovieDetailPage);
  await waitFor(() => rendered.container.querySelector('[data-testid="movie-title"]') !== null);

  // degraded:true details still render the full page.
  expect(rendered.container.querySelector('[data-testid="movie-detail-page"]').getAttribute('data-imdb')).toBe('tt555');
  expect(rendered.container.querySelector('[data-testid="movie-title"]').textContent).toBe('Blade Runner 2049');
  expect(rendered.container.querySelector('[data-testid="movie-year"]').textContent).toBe('2049');
  expect(rendered.container.querySelector('[data-testid="movie-rating"]').textContent).toBe('★ 8.1');
  expect(rendered.container.querySelector('[data-testid="movie-runtime"]').textContent).toBe('117m');
  expect(rendered.container.querySelector('[data-testid="movie-genres"]').textContent).toBe('Sci-Fi, Neo-noir');
  expect(rendered.container.querySelector('[data-testid="movie-cast"]').textContent).toBe('Aya Moreau, Sean Kovel');
  expect(rendered.container.querySelector('[data-testid="movie-synopsis"]').textContent).toContain('replica drifts');
  expect(rendered.container.querySelector('[data-testid="movie-poster"]')).toBeTruthy();
  expect(rendered.container.querySelector('[data-testid="movie-backdrop"]')).toBeTruthy();
  expect(rendered.container.querySelector('[data-testid="availability-badge"]').textContent).toBe('In Library');
  expect(rendered.container.querySelector('[data-testid="library-path"]').textContent).toBe('/movies/blade.runner.2049');

  // Release actions are usable despite the degraded flag.
  expect(rendered.container.querySelector('[data-testid="download-best"]')).toBeTruthy();
  expect(rendered.container.querySelector('[data-testid="choose-release"]')).toBeTruthy();

  // Related rail cards navigate to /movie/:id.
  rendered.container.querySelector('[data-testid="poster-card"][data-id="tt666"]').click();
  await waitFor(() => currentPath() === '/movie/tt666');
  expect(route()?.view).toBe('movie');

  // A failing details fetch degrades to the retry panel; Retry re-fetches.
  setLocation('/movie/tt777', '');
  await waitFor(() => rendered.container.querySelector('[data-testid="movie-error"]') !== null);
  expect(rendered.container.querySelector('[data-testid="movie-error-message"]').textContent).toContain('Details unavailable');
  installFetch({
    '/api/movie/tt777/details': detailBody('tt777', 'Seventeen Seventy-Seven', false, []),
  }, []);
  rendered.container.querySelector('[data-testid="movie-retry"]').click();
  await waitFor(() => rendered.container.querySelector('[data-testid="movie-title"]')?.textContent === 'Seventeen Seventy-Seven');
  expect(rendered.container.querySelector('[data-testid="movie-error"]')).toBeNull();
  restore();
});

test('Download Best queues the highest-score release and toasts with a /queue anchor', async () => {
  const downloadCalls: DownloadCall[] = [];
  installFetch(
    {
      '/api/movie/tt777/details': detailBody('tt777', 'Seventeen Seventy-Seven', false, []),
      '/api/releases/movie': mockReleases,
    },
    downloadCalls,
  );
  clearToasts();
  closeDrawer();
  setLocation('/movie/tt777', '');
  const rendered = render(MovieDetailPage);
  await waitFor(() => rendered.container.querySelector('[data-testid="movie-title"]') !== null);

  rendered.container.querySelector('[data-testid="download-best"]').click();
  await waitFor(() => downloadCalls.length === 1);
  // bestRelease: highest score (60) wins over the higher-seed 1080p rows.
  expect(downloadCalls[0]).toEqual({ force: false, title: 'Blade.Runner.2049.720p.HDTV.x264-GRP' });
  await waitFor(() => toasts().length === 1);
  const toast = toasts()[0];
  expect(toast.kind).toBe('success');
  expect(toast.message).toContain('Queued');
  expect(toast.actionPath).toBe('/queue');
  expect(bestRelease(mockReleases).title).toBe('Blade.Runner.2049.720p.HDTV.x264-GRP');
});

test('zero matching releases toast instead of queueing a phantom download', async () => {
  const downloadCalls: DownloadCall[] = [];
  installFetch(
    {
      '/api/movie/tt777/details': detailBody('tt777', 'Seventeen Seventy-Seven', false, []),
      '/api/releases/movie': [],
    },
    downloadCalls,
  );
  clearToasts();
  setLocation('/movie/tt777', '');
  const rendered = render(MovieDetailPage);
  await waitFor(() => rendered.container.querySelector('[data-testid="movie-title"]') !== null);
  rendered.container.querySelector('[data-testid="download-best"]').click();
  await waitFor(() => toasts().length === 1);
  expect(downloadCalls).toHaveLength(0);
  expect(toasts()[0].message).toBe('No matching releases found');
  expect(toasts()[0].kind).toBe('info');
});

test('drawer chips and sort buttons drive api filter/sort over the rows', async () => {
  installFetch(
    {
      '/api/movie/tt777/details': detailBody('tt777', 'Seventeen Seventy-Seven', false, []),
      '/api/releases/movie': mockReleases,
    },
    [],
  );
  setLocation('/movie/tt777', '');
  const rendered = render(MovieDetailPage);
  await waitFor(() => rendered.container.querySelector('[data-testid="movie-title"]') !== null);
  rendered.container.querySelector('[data-testid="choose-release"]').click();
  await waitFor(() => drawer() !== null && drawer()?.releases.length === mockReleases.length);
  expect(drawer()?.scope).toBe('movie');
  expect(drawer()?.open).toBe(true);
  const openRows = rendered.container.querySelectorAll('[data-testid="release-row"]');
  expect(openRows).toHaveLength(mockReleases.length);

  // Drawer metadata unit checks against the same mock rows.
  const chips1080 = filterReleases(mockReleases, '1080p');
  expect(chips1080.map((row) => row.title)).toEqual([
    'Blade.Runner.2049.1080p.BluRay.x264-GRP',
    'Blade.Runner.2049.1080p.WEB-DL.x265-GRP',
  ]);
  expect(sortReleases(mockReleases, 'seeds').map((row) => row.seeds)).toEqual([12, 9, 6, 2]);

  // Resolution chip filters the rendered rows.
  rendered.container.querySelector('[data-testid="drawer-chip"][data-chip="1080p"]').click();
  await waitFor(() => rendered.container.querySelectorAll('[data-testid="release-row"]').length === chips1080.length);
  const filtered = rendered.container.querySelectorAll('[data-testid="release-row"]');
  expect(Array.from(filtered).map((row) => row.getAttribute('data-title'))).toEqual(
    chips1080.map((row) => row.title),
  );

  // Sort control re-orders the filtered rows by seeders.
  rendered.container.querySelector('[data-testid="drawer-sort"][data-sort="seeds"]').click();
  const seededBySort = (): boolean => {
    const rows = rendered.container.querySelectorAll('[data-testid="release-row"]');
    return rows.length === chips1080.length && rows[0].getAttribute('data-title') === chips1080[1].title;
  };
  await waitFor(seededBySort);
  const seeded = rendered.container.querySelectorAll('[data-testid="release-row"]');
  expect(Array.from(seeded).map((row) => row.getAttribute('data-title'))).toEqual(
    sortReleases(chips1080, 'seeds').map((row) => row.title),
  );

  // One row carries title/indexer/score/seeds/size straight to the DOM.
  const top = seeded[0];
  expect(top.getAttribute('data-indexer')).toBe('Indexer C');
  expect(top.getAttribute('data-score')).toBe('25');
  expect(top.getAttribute('data-seeds')).toBe('12');
  expect(top.getAttribute('data-size')).toBe(formatBytes(6_400_000_000));

  // The drawer close button clears the global drawer state.
  rendered.container.querySelector('[data-testid="drawer-close"]').click();
  await waitFor(() => drawer() === null);
  expect(rendered.container.querySelectorAll('[data-testid="release-row"]')).toHaveLength(0);
});

test('Escape and backdrop click both dismiss the release drawer', async () => {
  installFetch(
    {
      '/api/movie/tt777/details': detailBody('tt777', 'Seventeen Seventy-Seven', false, []),
      '/api/releases/movie': mockReleases,
    },
    [],
  );
  setLocation('/movie/tt777', '');
  const rendered = render(MovieDetailPage);
  await waitFor(() => rendered.container.querySelector('[data-testid="movie-title"]') !== null);

  rendered.container.querySelector('[data-testid="choose-release"]').click();
  await waitFor(() => drawer() !== null);
  globalThis.window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
  await waitFor(() => drawer() === null);

  rendered.container.querySelector('[data-testid="choose-release"]').click();
  await waitFor(() => drawer() !== null);
  rendered.container.querySelector('[data-testid="drawer-backdrop"]').click();
  await waitFor(() => drawer() === null);
});

test('a duplicate 409 pauses on the confirmation; accept re-submits with force', async () => {
  const downloadCalls: DownloadCall[] = [];
  installFetch(
    {
      '/api/movie/tt888/details': detailBody('tt888', 'Dup Movie', false, []),
      '/api/releases/movie': [dupeRelease],
    },
    downloadCalls,
    true,
  );
  clearToasts();
  setLocation('/movie/tt888', '');
  const rendered = render(MovieDetailPage);
  await waitFor(() => rendered.container.querySelector('[data-testid="movie-title"]') !== null);
  rendered.container.querySelector('[data-testid="download-best"]').click();
  await waitFor(() => confirmation() !== null);
  const pending = confirmation();
  expect(pending?.kind).toBe('duplicate');
  expect(pending?.message).toBe('"Dup.Movie.2024.1080p.WEB.h264-GRP" is already in the library. Download it again?');
  expect(downloadCalls).toEqual([{ force: false, title: 'Dup.Movie.2024.1080p.WEB.h264-GRP' }]);

  answerConfirmation(true);
  await waitFor(() => downloadCalls.length === 2);
  expect(downloadCalls[1]).toEqual({ force: true, title: 'Dup.Movie.2024.1080p.WEB.h264-GRP' });
  await waitFor(() => toasts().length === 1);
  expect(toasts()[0].message).toContain('again');
  expect(confirmation()).toBeNull();
});

test('declining the duplicate confirmation leaves no second download call', async () => {
  const downloadCalls: DownloadCall[] = [];
  installFetch(
    {
      '/api/movie/tt888/details': detailBody('tt888', 'Dup Movie', false, []),
      '/api/releases/movie': [dupeRelease],
    },
    downloadCalls,
    true,
  );
  clearToasts();
  setLocation('/movie/tt888', '');
  const rendered = render(MovieDetailPage);
  await waitFor(() => rendered.container.querySelector('[data-testid="movie-title"]') !== null);
  rendered.container.querySelector('[data-testid="download-best"]').click();
  await waitFor(() => confirmation() !== null);
  answerConfirmation(false);
  await waitFor(() => confirmation() === null);
  expect(downloadCalls).toEqual([{ force: false, title: 'Dup.Movie.2024.1080p.WEB.h264-GRP' }]);
  expect(toasts()).toHaveLength(0);
  expect(rendered.container.querySelector('[data-testid="download-best"]')).toBeTruthy();
});
