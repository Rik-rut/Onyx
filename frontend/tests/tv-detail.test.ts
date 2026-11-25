import { expect, test } from 'vitest';
import { render } from '@testing-library/svelte';
import TvDetailPage from '../src/components/TvDetailPage.svelte';
import { currentPath, setLocation } from '../src/lib/router.svelte';
import { clearToasts, closeDrawer, drawer, toasts } from '../src/lib/stores/ui.svelte';
import { flushSync } from 'svelte';

declare const globalThis: {
  fetch: (path: string, options?: Record<string, unknown>) => {
    ok: boolean;
    status: number;
    statusText: string;
    text: () => Promise<string>;
  };
};

const realFetch = globalThis.fetch;

// Seeded show: two seasons; on-disk episodes come from the availability
// check (available_seasons seeds: season 1 -> ep 1, season 2 -> eps 1 and 3).
const detailsBody = {
  id: 7,
  title: 'Wayward Pines',
  year: 2015,
  imdb_id: 'tt5579750',
  tvdb_id: null,
  status: 'Ended',
  seasons: [
    {
      season_number: 1,
      episodes: [
        { episode_number: 1, name: 'White Tiger, Caught', air_date: '2015-07-06', available: true },
        { episode_number: 2, name: 'White Tiger, Escaped', air_date: '2015-07-13', available: false },
        { episode_number: 3, name: 'Do You Wish To Be Hunted?', air_date: null, available: false },
      ],
    },
    {
      season_number: 2,
      episodes: [
        { episode_number: 1, name: 'The End of the Beginning', air_date: '2015-08-10', available: true },
        { episode_number: 2, name: 'Kill Anyone to Save a Flower', air_date: '2015-08-17', available: false },
        { episode_number: 3, name: 'I Was, and I Will', air_date: '2015-08-24', available: true },
      ],
    },
  ],
  in_library: true,
  library_status: 'partial',
  monitored: false,
  available_seasons: { '1': [1], '2': [1, 3] },
  overview: 'A town where everyone keeps a secret.',
  rating: 7.6,
  genres: ['Mystery', 'Drama'],
  poster: '',
  network: 'FOX',
  similar: [
    { title: 'Twin Peaks', tmdb_id: 4001, poster: '', rating: 8.4, library_status: 'available' },
    { title: 'Lost', tmdb_id: 4002, poster: '', rating: 7.3 },
  ],
};

const seasonOneReleases = [
  {
    indexer: 'Indexer Alpha',
    title: 'Wayward.Pines.S01E01.WEB.x264-720p',
    infohash: 'aaa1',
    magnet: 'magnet:?xt=urn:btih:aaa1',
    seeds: 40,
    peers: 2,
    size_bytes: 384000000,
    resolution: '720p',
    codec: 'WEB-DL',
    source: 'WEB',
    score: 600,
    is_pack: false,
  },
  {
    indexer: 'Indexer Beta',
    title: 'Wayward.Pines.S01.Complete.1080p',
    infohash: 'bbb2',
    magnet: 'magnet:?xt=urn:btih:bbb2',
    seeds: 12,
    peers: 5,
    size_bytes: 1600000000,
    resolution: '1080p',
    codec: 'WEB',
    source: 'WEB',
    score: 900,
    is_pack: true,
  },
];

// Route-keyed mock; POST bodies are captured per bare path so assertions can
// inspect what the page actually sent (season args, monitor payloads).
function installMock(paths: string[], bodies: Record<string, string[]>): void {
  globalThis.fetch = (path: string, options?: Record<string, unknown>) => {
    const [bare, query] = [...path.split('?', 2), ''];
    paths.push(path);
    if (typeof options?.body === 'string') {
      bodies[bare] = [...(bodies[bare] ?? []), String(options.body)];
    }
    let payload: unknown = null;
    if (bare === '/api/tv/7/details' || bare === '/api/tv/4001/details') payload = detailsBody;
    else if (bare === '/api/series/monitor') payload = { status: 'monitored', id: 12, title: 'Wayward Pines' };
    else if (bare === '/api/releases/tv') {
      if (query.includes('pack=true')) payload = [];
      else if (query.includes('season=1')) payload = seasonOneReleases;
      else payload = [seasonOneReleases[0]];
    } else if (bare === '/api/queue/download/release') payload = { status: 'queued' };
    else throw new Error(`unmocked path ${bare}`);
    return { ok: true, status: 200, statusText: 'OK', text: async () => JSON.stringify(payload) };
  };
}

// Svelte schedules re-renders in microtasks; drain one microtask per round
// until the DOM/store condition holds, then give renders two extra hops.
const flush = async () => await null;

async function until(done: () => boolean): Promise<void> {
  for (let round = 0; round < 100; round += 1) {
    if (done()) {
      await flush();
      await flush();
      return;
    }
    await flush();
  }
  throw new Error('condition never became true');
}

test('the page paints from /api/tv/:id/details with metadata, tabs, and monitor control', async () => {
  clearToasts();
  closeDrawer();
  const paths: string[] = [];
  const bodies: Record<string, string[]> = {};
  installMock(paths, bodies);
  setLocation('/tv/7', '');
  const rendered = render(TvDetailPage);
  await until(() => rendered.container.querySelector('[data-testid="tv-show-card"]') !== null);
  expect(paths.filter((path) => path === '/api/tv/7/details').length).toBe(1);
  expect(
    rendered.container.querySelector('[data-testid="tv-show-card"] h1').textContent,
  ).toBe('Wayward Pines');
  const badge = rendered.container.querySelector('[data-testid="library-badge"]');
  expect(badge.getAttribute('data-status')).toBe('partial');
  expect(badge.textContent).toBe('Partially Available');
  expect(rendered.container.querySelector('[data-testid="rating-badge"]').textContent).toContain('7.6');
  const tabs = rendered.container.querySelectorAll('[data-testid="season-tab"]');
  expect(Array.from(tabs).map((tab) => tab.getAttribute('data-season'))).toEqual(['1', '2']);
  expect(tabs[0].getAttribute('data-active')).toBe('true');
  // Default season is the first one from the payload.
  expect(rendered.container.querySelector('[data-testid="episode-list"]').getAttribute('data-season')).toBe('1');
  expect(rendered.container.querySelectorAll('[data-testid="episode-row"]').length).toBe(3);
  // Monitor control starts unmonitored: chip says so, button offers the toggle.
  expect(rendered.container.querySelector('[data-testid="monitor-status"]').textContent).toBe('Unmonitored');
  expect(rendered.container.querySelector('[data-testid="monitor-toggle"]').textContent.trim()).toBe('+ Monitor');
  globalThis.fetch = realFetch;
});

test('switching to season 2 replaces the full-height episode list, on-disk eps badge', async () => {
  clearToasts();
  closeDrawer();
  const paths: string[] = [];
  const bodies: Record<string, string[]> = {};
  installMock(paths, bodies);
  setLocation('/tv/7', '');
  const rendered = render(TvDetailPage);
  await until(() => rendered.container.querySelector('[data-testid="tv-show-card"]') !== null);

  rendered.container.querySelector('[data-testid="season-tab"][data-season="2"]').click();
  // Svelte defers re-renders after reactive writes; flushSync applies them
  // before the assertions read the DOM.
  flushSync(() => {});

  // Exactly the season 2 episodes remain; the tab is the active one now.
  expect(rendered.container.querySelector('[data-testid="episode-list"]').getAttribute('data-season')).toBe('2');
  const rows = rendered.container.querySelectorAll('[data-testid="episode-row"]');
  expect(Array.from(rows).map((row) => row.getAttribute('data-episode'))).toEqual(['1', '2', '3']);
  const secondTab = rendered.container.querySelector('[data-testid="season-tab"][data-season="2"]');
  expect(secondTab.getAttribute('data-active')).toBe('true');

  // On-disk ids (seeded season 2 -> eps 1 and 3) get Available badges.
  const badges = rendered.container.querySelectorAll('[data-testid="episode-badge"]');
  expect(badges.length).toBe(2);
  Array.from(badges).forEach((badge) => {
    expect(badge.textContent).toBe('Available');
    expect(badge.getAttribute('data-status')).toBe('available');
  });
  expect(rendered.container.querySelector('[data-testid="episode-row"][data-episode="1"] [data-testid="episode-badge"]')).toBeTruthy();
  expect(rendered.container.querySelector('[data-testid="episode-row"][data-episode="3"] [data-testid="episode-badge"]')).toBeTruthy();
  expect(rendered.container.querySelector('[data-testid="episode-row"][data-episode="2"] [data-testid="episode-badge"]')).toBeNull();
  globalThis.fetch = realFetch;
});

test("'+ Monitor' posts the monitor call, flips the control, and toasts", async () => {
  clearToasts();
  closeDrawer();
  const paths: string[] = [];
  const bodies: Record<string, string[]> = {};
  installMock(paths, bodies);
  setLocation('/tv/7', '');
  const rendered = render(TvDetailPage);
  await until(() => rendered.container.querySelector('[data-testid="monitor-toggle"]') !== null);

  rendered.container.querySelector('[data-testid="monitor-toggle"]').click();
  flushSync(() => {});
  await until(() => (bodies['/api/series/monitor'] ?? []).length > 0);
  await until(() => toasts().length > 0);

  expect(paths.filter((path) => path === '/api/series/monitor').length).toBe(1);
  expect(bodies['/api/series/monitor'].length).toBe(1);
  const sent = JSON.parse(bodies['/api/series/monitor'][0]);
  expect(sent).toMatchObject({ tmdb_id: 7, title: 'Wayward Pines', imdb_id: 'tt5579750' });
  expect(rendered.container.querySelector('[data-testid="monitor-status"]').textContent).toBe('Monitoring');
  expect(rendered.container.querySelector('[data-testid="monitor-toggle"]').textContent.trim()).toBe('Unmonitor');
  expect(toasts()).toEqual([
    {
      kind: 'success',
      message: 'Now monitoring Wayward Pines',
    },
  ]);
  globalThis.fetch = realFetch;
});

test('Download Best season 1 queues the best release with the season arg', async () => {
  clearToasts();
  closeDrawer();
  const paths: string[] = [];
  const bodies: Record<string, string[]> = {};
  installMock(paths, bodies);
  setLocation('/tv/7', '');
  const rendered = render(TvDetailPage);
  await until(() => rendered.container.querySelector('[data-testid="download-best"]') !== null);

  rendered.container.querySelector('[data-testid="download-best"]').click();
  await until(() => (bodies['/api/queue/download/release'] ?? []).length > 0);
  await until(() => toasts().length > 0);
  flushSync(() => {});

  expect(paths.filter((path) => path.includes('/api/releases/tv')).length).toBe(1);
  const queued = JSON.parse(bodies['/api/queue/download/release'][0]);
  // The best release of the season-one results (highest score) is queued,
  // targeted at the show with its season number.
  expect(queued).toMatchObject({
    title: 'Wayward.Pines.S01.Complete.1080p',
    infohash: 'bbb2',
    media_type: 'tv',
    season: 1,
    tmdb_id: 7,
    display_title: 'Wayward Pines',
    force: false,
  });
  expect(toasts()).toEqual([
    {
      kind: 'success',
      message: 'Queued Wayward.Pines.S01.Complete.1080p for Wayward Pines season 1',
    },
  ]);
  globalThis.fetch = realFetch;
});

test('season packs with zero releases toast instead of opening an empty drawer', async () => {
  clearToasts();
  closeDrawer();
  const paths: string[] = [];
  const bodies: Record<string, string[]> = {};
  installMock(paths, bodies);
  setLocation('/tv/7', '');
  const rendered = render(TvDetailPage);
  await until(() => rendered.container.querySelector('[data-testid="season-pack-releases"]') !== null);

  rendered.container.querySelector('[data-testid="season-pack-releases"]').click();
  await until(() => paths.some((path) => path.includes('pack=true'))
    && toasts().length > 0);

  flushSync(() => {});
  const packCall = paths.find((path) => path.includes('pack=true')) ?? '';
  expect(packCall).toContain('title=Wayward%20Pines');
  expect(packCall).toContain('season=1');
  expect(toasts()).toEqual([
    { kind: 'info', message: 'No season packs found for Wayward Pines' },
  ]);
  expect(rendered.container.querySelector('[data-testid="drawer-empty"]')).toBeTruthy();
  expect(rendered.container.querySelector('[data-testid="release-row"]')).toBeNull();
  const opened = drawer();
  expect(opened?.scope).toBe('tv-season');
  expect(opened?.loading).toBe(false);
  expect(opened?.releases).toEqual([]);
  globalThis.fetch = realFetch;
});


test('drawer rows show coverage badge, raw name, and scope-aware title', async () => {
  clearToasts();
  closeDrawer();
  const paths: string[] = [];
  const bodies: Record<string, string[]> = {};

  const episodeReleases = [
    {
      indexer: 'EZTV',
      title: 'Wayward Pines S01E01',
      raw_title: 'Wayward.Pines.S01E01.1080p.WEB-DL.x264-GRP',
      infohash: 'ccc3',
      magnet: 'magnet:?xt=urn:btih:ccc3',
      seeds: 10,
      peers: 1,
      size_bytes: 500000000,
      resolution: '1080p',
      codec: 'WEB-DL',
      source: 'WEB',
      score: 700,
      is_pack: false,
      season: 1,
      episode: 1,
      seasons: null,
      season_label: 'S01E01',
    },
    {
      indexer: 'EZTV',
      title: 'Wayward Pines S01 COMPLETE',
      raw_title: 'Wayward.Pines.S01.COMPLETE.1080p.BluRay.x264-GRP',
      infohash: 'ddd4',
      magnet: 'magnet:?xt=urn:btih:ddd4',
      seeds: 30,
      peers: 2,
      size_bytes: 2000000000,
      resolution: '1080p',
      codec: 'BluRay',
      source: 'BluRay',
      score: 900,
      is_pack: true,
      season: null,
      episode: null,
      seasons: [1],
      season_label: 'S01',
    },
  ];

  globalThis.fetch = (path: string, options?: Record<string, unknown>) => {
    const [bare, query] = [...path.split('?', 2), ''];
    paths.push(path);
    if (typeof options?.body === 'string') {
      bodies[bare] = [...(bodies[bare] ?? []), String(options.body)];
    }
    let payload: unknown = null;
    if (bare === '/api/tv/7/details' || bare === '/api/tv/4001/details') payload = detailsBody;
    else if (bare === '/api/releases/tv') payload = episodeReleases;
    else if (bare === '/api/queue/download/release') payload = { status: 'queued' };
    else throw new Error(`unmocked path ${bare}`);
    return { ok: true, status: 200, statusText: 'OK', text: async () => JSON.stringify(payload) };
  };

  setLocation('/tv/7', '');
  const rendered = render(TvDetailPage);
  await until(() => rendered.container.querySelector('[data-testid="episode-releases"]') !== null);

  // Open the episode drawer for season 1, episode 1.
  const epBtn = rendered.container.querySelector('[data-testid="episode-releases"][data-episode="1"]');
  epBtn?.click();
  await until(() => rendered.container.querySelector('[data-testid="release-row"]') !== null);
  await until(() =>
    (rendered.container.querySelectorAll('[data-testid="release-row"]').length ?? 0) >= 2,
  );
  flushSync(() => {});

  // Scope-aware drawer title: requested show + S01E01.
  const drawerTitle = rendered.container.querySelector('[data-testid="drawer-title"]');
  expect(drawerTitle?.textContent).toContain('Wayward Pines');
  expect(drawerTitle?.textContent).toContain('S01E01');

  // Coverage badge text comes straight from the row's season_label. The drawer
  // sorts rows by score (pack 900 > episode 700), so the pack leads.
  const badges = Array.from(rendered.container.querySelectorAll('[data-testid="release-coverage"]'));
  expect(badges.map((badge) => badge.textContent)).toEqual(['S01', 'S01E01']);

  // The raw indexer name renders under the display title.
  const rawLines = Array.from(rendered.container.querySelectorAll('[data-testid="release-raw-title"]'));
  expect(rawLines.map((line) => line.textContent)).toEqual([
    'Wayward.Pines.S01.COMPLETE.1080p.BluRay.x264-GRP',
    'Wayward.Pines.S01E01.1080p.WEB-DL.x264-GRP',
  ]);

  // The pre-existing Season Pack badge still renders for pack rows.
  expect(rendered.container.textContent ?? '').toContain('Season Pack');

  globalThis.fetch = realFetch;
});

test('related shows render as PosterCards that navigate to /tv/:id', async () => {
  clearToasts();
  closeDrawer();
  const paths: string[] = [];
  const bodies: Record<string, string[]> = {};
  installMock(paths, bodies);
  setLocation('/tv/7', '');
  const rendered = render(TvDetailPage);
  await until(() => rendered.container.querySelector('[data-testid="tv-show-card"]') !== null);

  const rail = rendered.container.querySelector('[data-testid="media-rail"]');
  expect(rail?.getAttribute('data-rail')).toBe('More Like This');
  expect(rendered.container.querySelectorAll('[data-testid="media-rail"]').length).toBe(1);
  const related = rendered.container.querySelectorAll('[data-testid="poster-card"][data-kind="tv"]');
  expect(Array.from(related).map((card) => card.getAttribute('data-id'))).toEqual(['4001', '4002']);

  related[0].click();
  await flush();
  expect(currentPath()).toBe('/tv/4001');
  globalThis.fetch = realFetch;
});
