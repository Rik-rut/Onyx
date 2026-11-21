// Reactive Queue state: owns the /ws/queue connection (the backend polls
// Transmission every second and pushes a snapshot), aggregate transfer rates,
// reconnect backoff (1s -> 15s), and a REST fallback poll.
import { api, queueSocketUrl } from '../../lib/api';
import type { QueueItem } from '../../lib/api';

declare const globalThis: {
  WebSocket?: new (url: string) => Socket;
  setTimeout: (callback: () => void, ms: number) => unknown;
  location?: { protocol: string; host: string };
};

interface Socket {
  send(data: string): void;
  close(): void;
  addEventListener(type: string, handler: (event: { data?: string }) => void): void;
}

export const RETRY_FLOOR_MS = 1000;
export const RETRY_CEILING_MS = 15000;
export const GIVE_UP_AFTER_FAILURES = 3;

const transfer = $state({
  socket: null as Socket | null,
  torrents: [] as QueueItem[],
  receivedAt: 0,
  failures: 0,
  retryScheduled: false,
});

export function torrents(): QueueItem[] {
  return transfer.torrents;
}

export function wsConnected(): boolean {
  return transfer.socket !== null && transfer.failures === 0;
}

export function backendDown(): boolean {
  return transfer.failures >= GIVE_UP_AFTER_FAILURES;
}

export function retryDelayMs(): number {
  return Math.min(RETRY_CEILING_MS, RETRY_FLOOR_MS * 2 ** transfer.failures);
}

export function totalDownloadRate(): number {
  return transfer.torrents.reduce((sum, item) => sum + item.rate_download, 0);
}

export function totalUploadRate(): number {
  return transfer.torrents.reduce((sum, item) => sum + item.rate_upload, 0);
}

export function queueCount(): number {
  return transfer.torrents.length;
}

// Status grouping for the Queue filter pills.
export function statusGroup(item: QueueItem): 'active' | 'seeding' | 'paused' {
  if (item.status_code === 6 || item.status === 'Seeding') return 'seeding';
  if (item.status_code === 0 || item.status === 'Paused') return 'paused';
  return 'active';
}

export function snapshotUrl(): string {
  const location = globalThis.location ?? { protocol: 'http:', host: '127.0.0.1:3698' };
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${scheme}//${location.host}${queueSocketUrl}`;
}

export function acceptMessage(payload: string): void {
  const parsed = JSON.parse(payload);
  transfer.torrents = parsed.torrents;
  transfer.receivedAt = Number(parsed.timestamp) * 1000;
  transfer.failures = 0;
  transfer.retryScheduled = false;
}

function scheduleRetry(): void {
  if (transfer.retryScheduled || !globalThis.WebSocket) return;
  transfer.retryScheduled = true;
  const delay = retryDelayMs();
  transfer.failures += 1;
  globalThis.setTimeout(() => {
    transfer.retryScheduled = false;
    openSocket();
  }, delay);
}

export function openSocket(): void {
  const ctor = globalThis.WebSocket;
  if (!ctor) {
    // No WebSocket transport: keep the queue fresh over REST.
    void refreshFromRest();
    return;
  }
  try {
    const created = new ctor(snapshotUrl());
    created.addEventListener('message', (event) => acceptMessage(event.data ?? ''));
    created.addEventListener('error', () => scheduleRetry());
    created.addEventListener('close', () => scheduleRetry());
    transfer.socket = created;
    transfer.failures = 0;
  } catch (failure) {
    void failure;
    transfer.socket = null;
    scheduleRetry();
  }
}

export function closeSocket(): void {
  if (transfer.socket) transfer.socket.close();
  transfer.socket = null;
  transfer.retryScheduled = false;
  transfer.failures = 0;
}

// "Retry now" for the banner: resets the backoff and re-opens the socket
// (REST refresh when no WebSocket transport exists).
export async function retryNow(): Promise<void> {
  transfer.failures = 0;
  closeSocket();
  if (globalThis.WebSocket) openSocket();
  else await refreshFromRest();
}

export async function refreshFromRest(): Promise<void> {
  try {
    transfer.torrents = await api.queue();
    transfer.failures = 0;
  } catch (failure) {
    // Failures keep escalating so the backoff keeps growing past the point
    // where the banner appears.
    transfer.failures += 1;
  }
}
