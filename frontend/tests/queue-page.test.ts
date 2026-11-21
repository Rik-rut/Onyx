import { expect, test } from 'vitest';
import { fireEvent, render } from '@testing-library/svelte';
import { flushSync } from 'svelte';
import QueuePage from '../src/components/QueuePage.svelte';
import ConfirmDialog from '../src/components/ConfirmDialog.svelte';
import { currentPath, route } from '../src/lib/router.svelte';
import { formatBytes, formatEta, formatSpeed } from '../src/lib/api';
import { answerConfirmation, confirmation } from '../src/lib/stores/ui.svelte';
import {
  backendDown,
  refreshFromRest,
  retryDelayMs,
  statusGroup,
  torrents,
  wsConnected,
} from '../src/lib/stores/queue.svelte';

interface FetchOptions {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
}
interface Fetched {
  ok: boolean;
  status: number;
  statusText: string;
  text: () => Promise<string>;
}

declare const globalThis: {
  fetch: (path: string, options?: FetchOptions) => Fetched;
  WebSocket?: (url: string) => {
    send(data: string): void;
    close(): void;
    addEventListener(type: string, handler: (event: { data?: string }) => void): void;
  };
};

const realFetch = globalThis.fetch;

// jsdom's global WebSocket is the broken browser shim (ws/browser.js); removing
// it exercises the stores' documented REST fallback path in page tests.
globalThis.WebSocket = undefined;

// Router navigations call scrollTo; jsdom does not implement it.
window.scrollTo = () => {};

// Svelte schedules re-runs in microtasks; awaiting lets them settle.
const flush = async () => await null;
const settle = async (done: () => boolean, tries: number = 24) => {
  for (let attempt = 0; attempt < tries; attempt += 1) {
    if (done()) return;
    await flush();
  }
};

const activeRow = {
  id: 7,
  infohash: 'aaa7',
  name: 'Heat.2025.1080p.WEB.h264',
  progress: 42.5,
  status_code: 4,
  status: 'Downloading',
  rate_download: 1_500_000,
  rate_upload: 0,
  eta: 5_400,
  total_size: 8_000_000_000,
  media_type: 'movie',
  seeds: 61,
  created_at: 1_733_000_000,
  uploaded: 3_400_000_000,
  imdb_id: 'tt888',
};
const pausedRow = {
  id: 8,
  infohash: 'bbb8',
  name: 'The.Last.of.Us.S1E1',
  progress: 10,
  status_code: 0,
  status: 'Paused',
  rate_download: 0,
  rate_upload: 4_000,
  eta: -1,
  total_size: 512_000_000,
  media_type: 'tv',
  tmdb_id: 1403,
};
const erroredRow = {
  id: 9,
  infohash: 'ccc9',
  name: 'Broken.2024.720p',
  progress: 0,
  status_code: -1,
  status: 'Failed',
  rate_download: 0,
  rate_upload: 0,
  eta: -1,
  total_size: 900_000_000,
  media_type: null,
};
const queuedRow = {
  id: 10,
  infohash: 'ddd10',
  name: 'Dune.Part.Two.2021.4K',
  progress: 0,
  status_code: 3,
  status: 'Queue Pending',
  rate_download: 0,
  rate_upload: 0,
  eta: -1,
  total_size: 700_000_000,
  media_type: null,
};
const seedingRow = {
  id: 11,
  infohash: 'eee11',
  name: 'Planet.Earth.2024.2160p',
  progress: 100,
  status_code: 6,
  status: 'Seeding',
  rate_download: 0,
  rate_upload: 2_500_000,
  eta: -1,
  total_size: 12_000_000_000,
  media_type: null,
  seeds: 120,
  created_at: 1_732_900_000,
  uploaded: 12_000_000_000,
};

const allRows = [activeRow, pausedRow, erroredRow, queuedRow, seedingRow];

let failing = false;
let removedIds: number[] = [];
let calls: string[] = [];
let posts: Array<{ path: string; body: unknown }> = [];

const resetMock = () => {
  failing = false;
  removedIds = [];
  calls = [];
  posts = [];
};

const ok = (payload: unknown): Fetched => ({
  ok: true,
  status: 200,
  statusText: 'OK',
  text: async () => JSON.stringify(payload),
});

function serve(path: string, options?: FetchOptions): Fetched {
  calls.push(path);
  const [bare] = path.split('?');
  if (options?.method && options.method !== 'GET') {
    posts.push({ path: bare, body: options.body ? JSON.parse(options.body) : null });
  }
  if (failing) return { ok: false, status: 503, statusText: 'down', text: async () => '' };
  if (bare === '/api/queue') {
    return ok(allRows.filter((row) => !removedIds.includes(Number(row.id))));
  }
  if (/^\/api\/queue\/\d+\/(pause|resume|priority\/up|priority\/down)$/.test(bare)) return ok({ status: 'ok' });
  if (bare === '/api/queue/download/magnet') return ok({ status: 'queued' });
  if (bare === '/api/queue/import') return ok({ status: 'imported' });
  if (/^\/api\/queue\/\d+\/delete$/.test(bare)) {
    removedIds.push(Number(bare.split('/')[3]));
    return ok({ status: 'removed' });
  }
  throw new Error(`unmocked path ${bare}`);
}

globalThis.fetch = (path: string, options?: FetchOptions) => serve(path, options);

const rowNodes = (container: HTMLElement): Element[] =>
  Array.from(container.querySelectorAll('[data-testid="queue-row"]'));
const rowIds = (container: HTMLElement): Array<string | null> =>
  rowNodes(container).map((node) => node.getAttribute('data-id'));

test('status pills filter the visible torrents; All is the default and formatted cells remain', async () => {
  resetMock();
  const rendered = render(QueuePage);
  await refreshFromRest();
  await flush();

  const pills = () => Array.from(rendered.container.querySelectorAll<HTMLButtonElement>('[data-testid="queue-filter-pill"]'));
  expect(pills().map((pill) => pill.textContent)).toEqual(['All', 'Active', 'Seeding', 'Paused']);
  expect(pills().map((pill) => pill.getAttribute('data-filter'))).toEqual(['all', 'active', 'seeding', 'paused']);
  expect(pills()[0].getAttribute('data-active')).toBe('true');
  expect(pills()[0].getAttribute('aria-pressed')).toBe('true');
  expect(rowIds(rendered.container)).toEqual(['7', '8', '9', '10', '11']);

  // One shared list is filtered in place, rather than static status sections.
  pills()[2].click();
  flushSync(() => {});
  expect(rowIds(rendered.container)).toEqual(['11']);
  expect(rowNodes(rendered.container)[0].getAttribute('data-group')).toBe('seeding');
  expect(pills()[2].getAttribute('data-active')).toBe('true');
  expect(pills()[0].getAttribute('data-active')).toBe('false');

  pills()[3].click();
  flushSync(() => {});
  expect(rowIds(rendered.container)).toEqual(['8']);
  expect(rowNodes(rendered.container)[0].getAttribute('data-group')).toBe('paused');

  // Pending and failed rows share the Active bucket via statusGroup.
  pills()[1].click();
  flushSync(() => {});
  expect(rowIds(rendered.container)).toEqual(['7', '9', '10']);
  expect(statusGroup(queuedRow)).toBe('active');

  pills()[0].click();
  flushSync(() => {});
  expect(rowIds(rendered.container)).toEqual(['7', '8', '9', '10', '11']);
  expect(rendered.container.querySelector('[data-testid="queue-empty"]')).toBeNull();

  // Retained cell formatting: progress bar, eta, bytes, speed, seeds, date.
  const activeNode = rendered.container.querySelector('[data-testid="queue-row"][data-id="7"]');
  const bar = activeNode.querySelector('[data-testid="progress_percent"]');
  expect(bar.getAttribute('style')).toContain('width: 42.5%');
  expect(bar.getAttribute('data-progress')).toBe('42.5');
  expect(activeNode.querySelector('[data-testid="queue-eta"]').textContent).toBe(formatEta(5_400));
  expect(activeNode.querySelector('[data-testid="queue-size"]').textContent).toBe(formatBytes(8_000_000_000));
  expect(activeNode.querySelector('[data-testid="queue-download-rate"]').textContent).toBe(formatSpeed(1_500_000));
  expect(activeNode.querySelector('[data-testid="queue-uploaded"]').textContent).toBe(formatBytes(3_400_000_000));
  expect(activeNode.querySelector('[data-testid="queue-seeds"]').textContent).toBe('61');
  expect(activeNode.querySelector('[data-testid="queue-added"]').textContent).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
  const pausedNode = rendered.container.querySelector('[data-testid="queue-row"][data-id="8"]');
  expect(pausedNode.querySelector('[data-testid="queue-eta"]').textContent).toBe('—');
  expect(pausedNode.querySelector('[data-testid="queue-seeds"]').textContent).toBe('0');

  // Overall progress still averages every torrent, regardless of the filter.
  const overall = rendered.container.querySelector('[data-testid="queue-overall-progress-fill"]');
  expect(overall.getAttribute('data-progress')).toBe('31');
  expect(overall.getAttribute('style')).toContain('width: 31%');

  // Retained pause/resume controls and live socket indicator.
  expect(activeNode.querySelector('[data-testid="queue-pause"]')).toBeTruthy();
  expect(pausedNode.querySelector('[data-testid="queue-resume"]')).toBeTruthy();
  expect(activeNode.querySelector('[data-testid="queue-pause"]').textContent).toBe('Pause');
  activeNode.querySelector('[data-testid="queue-pause"]').click();
  pausedNode.querySelector('[data-testid="queue-resume"]').click();
  await settle(() => calls.includes('/api/queue/7/pause'));
  await settle(() => calls.includes('/api/queue/8/resume'));
  expect(calls.includes('/api/queue/7/pause')).toBe(true);
  expect(calls.includes('/api/queue/8/resume')).toBe(true);
  expect(wsConnected()).toBe(false);
  expect(rendered.container.querySelector('[data-testid="queue-connection"]').getAttribute('data-connected')).toBe('false');
  expect(rendered.container.querySelector('[data-testid="queue-connection-label"]').textContent).toBe('REST refresh fallback');

  // Raw Transmission status strings never surface inside a row.
  for (const [id, raw] of [['7', 'Downloading'], ['8', 'Paused'], ['9', 'Failed'], ['10', 'Queue Pending'], ['11', 'Seeding']]) {
    expect(rendered.container.querySelector(`[data-testid="queue-row"][data-id="${id}"]`).textContent).not.toContain(raw);
  }
});

test('magnet ingestion bar posts a magnet and Run Import Now posts an import', async () => {
  resetMock();
  const rendered = render(QueuePage);
  await refreshFromRest();
  await flush();

  const input = rendered.container.querySelector<HTMLInputElement>('[data-testid="magnet-input"]');
  const submit = rendered.container.querySelector<HTMLButtonElement>('[data-testid="magnet-submit"]');
  expect(input).toBeTruthy();
  expect(submit.disabled).toBe(true);

  await fireEvent.input(input, { target: { value: '  magnet:?xt=urn:btih:abc123  ' } });
  flushSync(() => {});
  expect(submit.disabled).toBe(false);
  submit.click();
  await settle(() => posts.some((post) => post.path === '/api/queue/download/magnet') && input.value === '');

  expect(posts.find((post) => post.path === '/api/queue/download/magnet')?.body).toEqual({
    magnet: 'magnet:?xt=urn:btih:abc123',
  });
  expect(input.value).toBe('');
  expect(submit.disabled).toBe(true);
  expect(calls.includes('/api/queue')).toBe(true);

  rendered.container.querySelector<HTMLButtonElement>('[data-testid="import-now"]').click();
  await settle(() => posts.some((post) => post.path === '/api/queue/import'));
  expect(posts.some((post) => post.path === '/api/queue/import')).toBe(true);
});

test('priority buttons post queue actions without navigating', async () => {
  resetMock();
  const rendered = render(QueuePage);
  await refreshFromRest();
  await flush();
  const before = currentPath();

  const row = rendered.container.querySelector('[data-testid="queue-row"][data-id="7"]');
  row.querySelector('[data-testid="priority-up"]').click();
  await settle(() => posts.some((post) => post.path === '/api/queue/7/priority/up'));
  row.querySelector('[data-testid="priority-down"]').click();
  await settle(() => posts.some((post) => post.path === '/api/queue/7/priority/down'));

  expect(posts.some((post) => post.path === '/api/queue/7/priority/up')).toBe(true);
  expect(posts.some((post) => post.path === '/api/queue/7/priority/down')).toBe(true);
  expect(currentPath()).toBe(before);
});

test('delete is confirmation-gated through the global ConfirmDialog', async () => {
  resetMock();
  const rendered = render(QueuePage);
  const dialog = render(ConfirmDialog);
  await refreshFromRest();
  await flush();

  const targetRow = () => rendered.container.querySelector('[data-testid="queue-row"][data-id="7"]');
  const deleteButton = targetRow().querySelector('[data-testid="delete-torrent"]');
  expect(deleteButton.textContent).toBe('Cancel + delete');
  deleteButton.click();
  await flush();

  // The delete pauses while the dialog awaits its answer.
  expect(confirmation()?.id).toBe('cancelDownload');
  expect(confirmation()?.kind).toBe('danger');
  expect(confirmation()?.message).toBe('Remove "Heat.2025.1080p.WEB.h264" from the queue?');
  expect(dialog.container.querySelector('[data-testid="confirm-dialog"]')).toBeTruthy();
  expect(dialog.container.querySelector('[data-testid="confirm-message"]').textContent).toBe(confirmation()?.message);
  expect(posts.some((post) => post.path === '/api/queue/7/delete')).toBe(false);
  expect(targetRow()).toBeTruthy();

  // Accepting in the dialog performs POST delete + a fresh snapshot.
  dialog.container.querySelector('[data-testid="confirm-accept"]').click();
  await settle(() => torrents().every((row) => Number(row.id) !== 7));
  await flush();
  expect(posts.find((post) => post.path === '/api/queue/7/delete')?.body).toEqual({ confirm: true });
  expect(torrents().every((row) => Number(row.id) !== 7)).toBe(true);
  expect(targetRow()).toBeNull();
  expect(confirmation()).toBeNull();

  // Refusing via the dialog keeps the row and never sends the delete.
  const otherRow = rendered.container.querySelector('[data-testid="queue-row"][data-id="10"]');
  otherRow.querySelector('[data-testid="delete-torrent"]').click();
  await flush();
  expect(confirmation()?.message).toBe('Remove "Dune.Part.Two.2021.4K" from the queue?');
  dialog.container.querySelector('[data-testid="confirm-cancel"]').click();
  await flush();
  expect(confirmation()).toBeNull();
  expect(posts.some((post) => post.path === '/api/queue/10/delete')).toBe(false);
  expect(torrents().some((row) => Number(row.id) === 10)).toBe(true);

  // The exported helper still resolves a pending confirmation directly.
  answerConfirmation(false);
  expect(confirmation()).toBeNull();
});

test('a dead backend raises the retry countdown and Retry Now recovers', async () => {
  resetMock();
  failing = true;
  const rendered = render(QueuePage);
  await refreshFromRest();
  await refreshFromRest();
  for (let attempt = 0; attempt < 6 && retryDelayMs() < 15_000; attempt += 1) await refreshFromRest();
  await settle(() => backendDown() && retryDelayMs() === 15_000);
  expect(backendDown()).toBe(true);

  const countdown = rendered.container.querySelector('[data-testid="retry-countdown"]');
  expect(countdown.getAttribute('data-retry-ms')).toBe(String(retryDelayMs()));
  expect(countdown.textContent).toContain(`${formatEta(retryDelayMs() / 1000)} until the next queue retry`);

  failing = false;
  rendered.container.querySelector('[data-testid="queue-retry-now"]').click();
  await settle(() => torrents().length === allRows.length && retryDelayMs() === 1_000);
  await flush();
  expect(backendDown()).toBe(false);
  expect(rendered.container.querySelector('[data-testid="retry-countdown"]')).toBeNull();
  expect(rowIds(rendered.container).length).toBe(allRows.length);
  expect(calls.includes('/api/queue')).toBe(true);
});

test('row clicks jump to the match route', async () => {
  resetMock();
  const rendered = render(QueuePage);
  await refreshFromRest();
  await flush();

  const nameLink = (id: string) => rendered.container.querySelector(`[data-testid="queue-row"][data-id="${id}"] [data-testid="queue-name"]`);

  nameLink('7').click();
  await flush();
  expect(currentPath()).toBe('/movie/tt888');

  nameLink('8').click();
  await flush();
  expect(currentPath()).toBe('/tv/1403');

  nameLink('9').click();
  await flush();
  expect(currentPath()).toBe('/library');
  expect(route()?.params?.q).toBe('Broken.2024.720p');

  nameLink('11').click();
  await flush();
  expect(currentPath()).toBe('/library');
  expect(route()?.params?.q).toBe('Planet.Earth.2024.2160p');

  globalThis.fetch = realFetch;
});
