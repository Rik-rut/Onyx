// /search?q= results store: the movies and TV sources fetch concurrently
// (Promise.all over per-source withResolvers guards), so a dead indexer only
// darkens its own panel; retry() targets just the failed sources.
import { api } from '../../lib/api';
import { ApiError } from '../../lib/api';
import type { MediaItem } from '../../lib/api';
import { rememberSearch } from '../../lib/stores/ui.svelte';

interface SourceResult {
  items: MediaItem[];
  error: string | null;
}

const box = $state({
  query: '',
  movies: [] as MediaItem[],
  tv: [] as MediaItem[],
  moviesError: null as string | null,
  tvError: null as string | null,
});

const searchSources: Array<'movies' | 'tv'> = ['movies', 'tv'];

const fetchers: Record<'movies' | 'tv', (query: string) => Promise<MediaItem[]>> = {
  movies: (query) => api.searchMovies(query),
  tv: (query) => api.searchTv(query),
};

// Plain module var on the perform guard: the page effect calls perform() on
// every re-run, and $state read here would be tracked into that same effect.
let attemptedQuery: string | null = null;

function describeFailure(failure: unknown): string {
  if (failure instanceof ApiError) return `${failure.detail} (HTTP ${failure.status})`;
  return String(failure);
}

// Bridge one source through a resolver guard: its rejection becomes a
// per-source result, so Promise.all over the pair never aborts on one side.
function guarded(fetcher: () => Promise<MediaItem[]>): Promise<SourceResult> {
  const { promise, resolve, reject } = Promise.withResolvers<MediaItem[]>();
  fetcher().then((items) => resolve(items), (failure) => reject(failure));
  return promise
    .then((items) => ({ items, error: null }) as SourceResult)
    .catch((failure) => ({ items: [] as MediaItem[], error: describeFailure(failure) } as SourceResult));
}

// Both fetchers are invoked synchronously here, so every request is issued
// before any response resolves — the parallelism tests assert.
let pendingAttempt: Promise<void> = Promise.resolve();

function runSearch(sources: Array<'movies' | 'tv'>, query: string): Promise<void> {
  pendingAttempt = Promise.all(
    sources.map((source) => guarded(() => fetchers[source](query))),
  ).then(
    (results) => {
      for (let index = 0; index < sources.length; index += 1) {
        const result = results[index];
        if (sources[index] === 'movies') {
          box.movies = result.items;
          box.moviesError = result.error;
        } else {
          box.tv = result.items;
          box.tvError = result.error;
        }
      }
    },
  );
  return pendingAttempt;
}

function failedSources(): Array<'movies' | 'tv'> {
  const failed: Array<'movies' | 'tv'> = [];
  if (box.moviesError !== null) failed.push('movies');
  if (box.tvError !== null) failed.push('tv');
  return failed;
}

export function perform(query: string): Promise<void> {
  const trimmed = query.trim();
  // Same query already attempted: keep the current results (a page effect
  // re-runs this on every store write, so the guard must short-circuit).
  if (trimmed !== '' && trimmed === attemptedQuery) return pendingAttempt;
  attemptedQuery = trimmed;
  box.query = trimmed;
  box.movies = [];
  box.tv = [];
  box.moviesError = null;
  box.tvError = null;
  rememberSearch(trimmed);
  return runSearch(searchSources, trimmed);
}

// Re-request only the sources that failed on the last attempt.
export function retry(): Promise<void> {
  const failed = failedSources();
  if (failed.length === 0) return pendingAttempt;
  return runSearch(failed, box.query);
}

export function retryMovies(): Promise<void> {
  return runSearch(['movies'], box.query);
}

export function retryTv(): Promise<void> {
  return runSearch(['tv'], box.query);
}

// The in-flight attempt resolves once every guarded source has written its
// slice; callers/tests await it instead of guessing microtask hops.
export function lastAttempt(): Promise<void> {
  return pendingAttempt;
}

export function queryText(): string {
  return box.query;
}

export function movies(): MediaItem[] {
  return box.movies;
}

export function tv(): MediaItem[] {
  return box.tv;
}

export function errors(): { movies: string | null; tv: string | null } {
  return { movies: box.moviesError, tv: box.tvError };
}
