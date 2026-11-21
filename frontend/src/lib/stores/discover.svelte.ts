// Reactive Discover feed: lazily fetches /api/discover once and keeps a
// scheduled retry window so a failed scrape degrades to an error panel instead
// of blanking the page.
import { api } from '../../lib/api';
import type { DiscoverPayload } from '../../lib/api';

declare const globalThis: {
  setTimeout: (callback: () => void, ms: number) => unknown;
};

export const RETRY_MS = 5000;

const feed = $state({
  payload: null as DiscoverPayload | null,
  failures: 0,
  loading: false,
  retryScheduled: false,
});

let pendingAttempt: Promise<DiscoverPayload | null> = Promise.resolve(null);

function attempt(): Promise<DiscoverPayload | null> {
  feed.retryScheduled = false;
  feed.loading = true;
  pendingAttempt = api.discover().then(
    (value) => {
      feed.payload = value;
      feed.failures = 0;
      feed.loading = false;
      return value;
    },
    () => {
      feed.failures += 1;
      feed.loading = false;
      if (!feed.retryScheduled) {
        feed.retryScheduled = true;
        globalThis.setTimeout(() => void attempt(), RETRY_MS);
      }
      return null;
    },
  );
  return pendingAttempt;
}

export function lastAttempt(): Promise<DiscoverPayload | null> {
  return pendingAttempt;
}

export function ensureLoaded(): void {
  if (feed.payload || feed.loading || feed.retryScheduled) return;
  attempt();
}

export function retryNow(): Promise<DiscoverPayload | null> {
  return attempt();
}

export function payload(): DiscoverPayload | null {
  return feed.payload;
}

export function isLoading(): boolean {
  return feed.loading && !feed.payload;
}

export function failures(): number {
  return feed.failures;
}

export function errorText(): string {
  if (feed.payload) return '';
  if (feed.failures === 0) return 'Loading the Discover rails…';
  return `Discover unavailable (${feed.failures} attempt${feed.failures === 1 ? '' : 's'}) — retrying in ${RETRY_MS / 1000}s`;
}
