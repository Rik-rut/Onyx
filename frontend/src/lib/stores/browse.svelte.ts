// Reactive browse feed for /movies and /tv: paginates /api/discover/browse via
// a bottom sentinel IntersectionObserver (with a MutationObserver fallback in
// jsdom environments where IntersectionObserver is absent).
import { api } from '../../lib/api';
import type { BrowsePayload, MediaItem } from '../../lib/api';

declare const globalThis: {
  document?: {
    querySelectorAll: (selector: string) => { length: number; item: (index: number) => unknown };
  };
};

interface GridNode {
  children: { length: number };
}

const feed = $state({
  items: [] as MediaItem[],
  page: 0,
  pageSize: 20,
  total: Infinity,
  hasMore: true,
  lastCount: 0,
  fetched: false,
  loading: false,
  error: null as string | null,
  key: '',
});

let pendingFetch: Promise<BrowsePayload | null> = Promise.resolve(null);
let queuedKey: string | null = null;
let hookedTarget: unknown = null;
let stopHook = (): void => void 0;

const activeKey = (mediaType: 'movie' | 'tv', genre: string): string =>
  `${mediaType} ${genre}`;

const exhausted = (): boolean => {
  if (!feed.fetched) return false;
  if (!feed.hasMore) return true;
  if (Number.isFinite(feed.total) && feed.items.length >= feed.total) return true;
  if (feed.lastCount === 0 || feed.lastCount < feed.pageSize) return true;
  return false;
};

function rowCount(grid: unknown): number {
  try {
    return (grid as GridNode).children.length;
  } catch {
    return 0;
  }
}

export function resetList(): void {
  feed.items = [];
  feed.page = 0;
  feed.pageSize = 20;
  feed.total = Infinity;
  feed.hasMore = true;
  feed.lastCount = 0;
  feed.fetched = false;
  feed.loading = false;
  feed.error = null;
  queuedKey = null;
}

function appendPage(mediaType: 'movie' | 'tv', genre: string, payload: BrowsePayload): void {
  if (feed.key !== activeKey(mediaType, genre)) return;
  const raw = payload as unknown as Record<string, unknown>;
  const page = Number(raw.page);
  if (page !== feed.page + 1) return;
  const rows = Array.isArray(raw.items) ? (raw.items as MediaItem[]) : [];
  const size = Number(raw.page_size);
  const total = Number(raw.total);
  const declaredHasMore = typeof raw.has_more === 'boolean' ? raw.has_more : null;

  feed.page = page;
  if (size > 0) feed.pageSize = size;
  else if (page === 1 && rows.length > 0) feed.pageSize = rows.length;
  if (Number.isFinite(total)) feed.total = total;
  if (declaredHasMore !== null) feed.hasMore = declaredHasMore;
  else feed.hasMore = rows.length > 0 && rows.length >= feed.pageSize;

  feed.lastCount = rows.length;
  feed.fetched = true;
  feed.loading = false;
  feed.error = null;

  // Deduplicate by imdb_id / tmdb_id / id so repeated items across pages never flicker.
  const seen = new Set(
    feed.items.map((item) => String(item.imdb_id ?? item.tmdb_id ?? item.id ?? item.title ?? '')),
  );
  const fresh = rows.filter((item) => {
    const id = String(item.imdb_id ?? item.tmdb_id ?? item.id ?? item.title ?? '');
    if (!id || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
  feed.items = [...feed.items, ...fresh];
}

export function loadPage(mediaType: 'movie' | 'tv', genre: string, page: number): Promise<BrowsePayload | null> {
  feed.loading = true;
  const request = api.browse(mediaType, genre, page).then(
    (payload) => {
      appendPage(mediaType, genre, payload);
      return payload;
    },
    (err) => {
      if (feed.key === activeKey(mediaType, genre)) {
        feed.loading = false;
        feed.error = err instanceof Error ? err.message : 'Could not load titles.';
      }
      return null;
    },
  );
  pendingFetch = request;
  return request;
}

export function refresh(mediaType: 'movie' | 'tv', genre: string): Promise<BrowsePayload | null> {
  const key = activeKey(mediaType, genre);
  if (feed.key === key && (feed.fetched || feed.loading)) return pendingFetch;
  if (feed.key !== key) {
    resetList();
    feed.key = key;
  }
  feed.loading = true;
  pendingFetch = loadPage(mediaType, genre, 1);
  return pendingFetch;
}

export function loadMore(mediaType: 'movie' | 'tv', genre: string): Promise<BrowsePayload | null> {
  const key = activeKey(mediaType, genre);
  if (feed.key !== key || !feed.fetched || feed.loading || queuedKey === key || exhausted()) return pendingFetch;
  queuedKey = key;
  void loadPage(mediaType, genre, feed.page + 1);
  pendingFetch = pendingFetch.then((payload) => {
    queuedKey = null;
    return payload;
  });
  return pendingFetch;
}

// Observes a bottom sentinel in real browsers (root: null with 320px lookahead)
// and falls back to MutationObserver on the grid in jsdom where IntersectionObserver
// is absent.
function attachHook(grid: unknown, sentinel: unknown, handle: () => void): () => void {
  try {
    if (typeof IntersectionObserver === 'function' && sentinel) {
      const observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) handle();
        },
        { root: null, rootMargin: '320px 0px' },
      );
      observer.observe(sentinel as Element);
      return (): void => void observer.disconnect();
    }
  } catch {
    // Fall through to MutationObserver in non-browser harnesses.
  }
  try {
    if (typeof MutationObserver === 'function' && grid) {
      const observer = new MutationObserver(() => handle());
      observer.observe(grid as Node, { childList: true });
      return (): void => void observer.disconnect();
    }
  } catch {
    // No observer available.
  }
  return (): void => void 0;
}

export function ensureVisible(
  grid: unknown,
  rows: number,
  onMore: () => void,
  sentinel?: unknown,
): void {
  const target = sentinel ?? grid;
  if (target && target !== hookedTarget) {
    stopHook();
    hookedTarget = target;
    stopHook = attachHook(grid, sentinel ?? grid, onMore);
  }
  if (rows > 0 && !exhausted() && typeof IntersectionObserver !== 'function') {
    onMore();
  }
}

export function gridHost(): unknown {
  const list = globalThis.document?.querySelectorAll('[data-testid="browse-grid"]');
  if (!list || list.length === 0) return null;
  return list.item(list.length - 1);
}

export function sentinelHost(): unknown {
  const list = globalThis.document?.querySelectorAll('[data-testid="browse-sentinel"]');
  if (!list || list.length === 0) return null;
  return list.item(list.length - 1);
}

export function gridRows(): number {
  return rowCount(gridHost());
}

export function visible(): MediaItem[] {
  return feed.items;
}

export function feedGenres(): string[] {
  const seen = new Set<string>();
  for (const item of feed.items) {
    for (const genre of item.genres ?? []) {
      if (genre) seen.add(genre);
    }
  }
  return [...seen].sort();
}

export function isLoading(): boolean {
  return feed.loading;
}

export function errorMessage(): string | null {
  return feed.error;
}

export function hasMore(): boolean {
  return !exhausted();
}

export function noResults(): boolean {
  return feed.fetched && feed.items.length === 0 && feed.error === null;
}

export function lastLoad(): Promise<BrowsePayload | null> {
  return pendingFetch;
}
