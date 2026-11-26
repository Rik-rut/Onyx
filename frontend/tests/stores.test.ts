import { expect, test } from 'vitest';
import { acceptMessage, backendDown, closeSocket, openSocket, queueCount, refreshFromRest, retryDelayMs, statusGroup, torrents, totalDownloadRate, totalUploadRate, wsConnected } from '../src/lib/stores/queue.svelte';
import { fetchStatus } from '../src/lib/stores/auth.svelte';
import { findMovie, invalidate, isCached, libraryCount, localMatches, refresh, seededTitles } from '../src/lib/stores/library.svelte';
import {
  askConfirmation,
  clearToasts,
  closeDrawer,
  confirmation,
  drawer,
  openDrawer,
  palette,
  pushToast,
  recentSearches,
  rememberSearch,
  answerConfirmation,
  setDrawerReleases,
  setPalette,
  setSidebarCollapsed,
  sidebarCollapsed,
  toasts,
} from '../src/lib/stores/ui.svelte';

declare const globalThis: {
  fetch: (path: string, options?: Record<string, unknown>) => {
    ok: boolean;
    status: number;
    statusText: string;
    text: () => Promise<string>;
  };
  WebSocket?: (url: string) => Record<string, unknown>;
  location?: { protocol: string; host: string };
  localStorage?: {
    getItem: (key: string) => string | null;
    setItem: (key: string, value: string) => void;
  };
  setTimeout: (callback: () => void, ms: number) => unknown;
};

const realFetch = globalThis.fetch;
const realWebSocket = globalThis.WebSocket;

function installFetch(routes: Record<string, unknown>, calls: string[]): void {
  globalThis.fetch = (path: string) => {
    const [bare] = path.split('?');
    calls.push(path);
    if (bare in routes) {
      return { ok: true, status: 200, statusText: 'OK', text: async () => JSON.stringify(routes[bare]) };
    }
    throw new Error('unmocked path');
  };
}

function restore(): void {
  globalThis.fetch = realFetch;
}

test('queue snapshot drives aggregate rates', async () => {
  acceptMessage(JSON.stringify({
    timestamp: 1_700_000_000,
    torrents: [
      { hash: 'a', status: 'Downloading', status_code: 4, progress: 50, size: 1000, downloaded: 500, rate_download: 250, rate_upload: 0, seeds: 5, leechers: 2, uploaded: 0, ratio: 0, eta: 200, filename: 'A', error: null },
      { hash: 'b', status: 'Seeding', status_code: 6, progress: 100, size: 2000, downloaded: 2000, rate_download: 0, rate_upload: 40, seeds: 9, leechers: 1, uploaded: 100, ratio: 0.05, eta: null, filename: 'B', error: null },
    ],
  }));
  expect(queueCount()).toBe(2);
  expect(totalDownloadRate()).toBe(250);
  expect(totalUploadRate()).toBe(40);
  expect(statusGroup(torrents()[0])).toBe('active');
  expect(statusGroup(torrents()[1])).toBe('seeding');
  expect(statusGroup({ status: 'Paused', status_code: 0 })).toBe('paused');
  acceptMessage(JSON.stringify({ timestamp: 1, torrents: [] }));
  expect(totalDownloadRate()).toBe(0);
});

test('backoff doubles per failure to the ceiling', async () => {
  const snapshot = torrents();
  expect(snapshot.length).toBe(0);
  expect(retryDelayMs()).toBe(1000);
  acceptMessage(JSON.stringify({ timestamp: 1, torrents: [] }));
  // Failures escalate through the failing REST path.
  installFetch({}, []);
  await refreshFromRest();
  expect(retryDelayMs()).toBe(2000);
  await refreshFromRest();
  expect(retryDelayMs()).toBe(4000);
  await refreshFromRest();
  expect(retryDelayMs()).toBe(8000);
  await refreshFromRest();
  expect(retryDelayMs()).toBe(15000);
  expect(backendDown()).toBe(true);
  restore();
});

test('socket handshake records url and handlers', async () => {
  // The socket is an authenticated resource; establish the session first.
  globalThis.fetch = (path) =>
    path.startsWith('/api/auth/status')
      ? {
          ok: true,
          status: 200,
          statusText: 'OK',
          text: async () =>
            JSON.stringify({
              authenticated: true,
              username: 'admin',
              must_change_credentials: false,
            }),
        }
      : { ok: false, status: 503, statusText: 'no mock', text: async () => '' };
  await fetchStatus();
  const opened: string[] = [];
  const fired: string[] = [];
  const handlers = new Map<string, (event: { data?: string }) => void>();
  class Stub {
    constructor(url: string) {
      opened.push(url);
    }
    send(data: string): void {
      void data;
    }
    close(): void {
      fired.push('close');
    }
    addEventListener(type: string, handler: (event: { data?: string }) => void): void {
      handlers.set(type, handler);
    }
  }
  globalThis.WebSocket = Stub as typeof globalThis.WebSocket;
  // The jsdom environment url (http://127.0.0.1:3698/) supplies the origin.
  openSocket();
  expect(opened).toEqual(['ws://127.0.0.1:3698/ws/queue']);
  expect(wsConnected()).toBe(true);
  handlers.get('message')?.({ data: JSON.stringify({ timestamp: 5, torrents: [] }) });
  expect(wsConnected()).toBe(true);
  closeSocket();
  expect(wsConnected()).toBe(false);
  globalThis.WebSocket = realWebSocket;
  globalThis.fetch = realFetch;
});

test('library cache answers locally', async () => {
  const calls: string[] = [];
  installFetch({ '/api/library': {
    movies: [
      { title: 'Heat', imdb_id: 'tt1', year: 2025, path: '/movies/heat.mkv', seeding: true },
      { title: 'Dune', imdb_id: 'tt2', year: 2021, path: '/movies/dune.mkv', seeding: false },
    ],
    shows: [{ title: 'The Last of Us', tmdb_id: 1403, path: '/tv/lou', seasons: [1], seeding: true }],
    sync: {},
  } }, calls);
  await refresh();
  expect(libraryCount()).toBe(3);
  expect(seededTitles()).toBe(2);
  expect(findMovie('tt1')?.title).toBe('Heat');
  expect(localMatches('he', 1).map((item) => item.name)).toEqual(['Heat']);
  // Palette typing must not touch the network.
  expect(localMatches('dun', 5).length).toBe(1);
  expect(calls).toEqual(['/api/library']);
  invalidate();
  expect(isCached()).toBe(false);
  expect(libraryCount()).toBe(0);
  restore();
});

test('shell preferences and dialogs', async () => {
  const written: Record<string, string> = {};
  globalThis.localStorage = {
    getItem: (key: string) => written[key],
    setItem: (key: string, value: string) => void (written[key] = value),
  } as typeof globalThis.localStorage;
  setSidebarCollapsed(true);
  expect(sidebarCollapsed()).toBe(true);
  expect(written['onyx.sidebar-collapsed']).toBe('true');
  globalThis.localStorage = undefined as typeof globalThis.localStorage;

  rememberSearch('heat');
  rememberSearch('dune');
  rememberSearch('heat');
  expect(recentSearches()).toEqual(['heat', 'dune']);
  expect(palette()).toEqual({ open: false, query: '' });
  setPalette(true, 'hea');
  expect(palette().query).toBe('hea');

  pushToast({ message: 'queued', kind: 'success', actionLabel: 'Queue', actionPath: '/queue' });
  pushToast({ message: 'offline', kind: 'error' });
  expect(toasts().length).toBe(2);
  clearToasts();
  expect(toasts()).toEqual([]);

  const awaiting = askConfirmation({
    id: 'delete-heat',
    title: 'Delete?',
    message: 'removes 4 files',
    kind: 'danger',
    actionPath: '/library',
  });
  expect(confirmation()?.kind).toBe('danger');
  const answered = answerConfirmation(true);
  expect(answered?.title).toBe('Delete?');
  expect(confirmation()).toBe(null);
  expect(await awaiting).toBe(true);

  openDrawer('movie', { imdb_id: 'tt1' });
  expect(drawer()?.loading).toBe(true);
  expect(drawer()?.releases).toEqual([]);
  setDrawerReleases([{ title: 'x' }], false);
  expect(drawer()?.releases.length).toBe(1);
  closeDrawer();
  expect(drawer()).toBe(null);
});
