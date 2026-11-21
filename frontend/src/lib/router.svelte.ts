// Typed History-API router. FastAPI serves the SPA document for every non-API
// path, so client routes must round-trip through reloads and Back/Forward.
export type RouteView =
  | 'discover'
  | 'movies'
  | 'tv'
  | 'search'
  | 'movie'
  | 'tvshow'
  | 'library'
  | 'monitored'
  | 'queue'
  | 'settings';

export interface Match {
  view: RouteView;
  params: Record<string, string>;
}

// Query parameters the SPA understands; anything else is dropped.
const QUERY_KEYS: ReadonlyArray<string> = ['q', 'genre'];

const STATIC_VIEWS: ReadonlyArray<[string, RouteView]> = [
  ['', 'discover'],
  ['/movies', 'movies'],
  ['/tv', 'tv'],
  ['/search', 'search'],
  ['/library', 'library'],
  ['/monitored', 'monitored'],
  ['/queue', 'queue'],
  ['/settings', 'settings'],
];

function parseQuery(query: string): Record<string, string> {
  const params: Record<string, string> = {};
  if (!query) return params;
  const pairs = query.startsWith('?') ? query.slice(1).split('&') : query.split('&');
  for (const pair of pairs) {
    if (!pair) continue;
    const [rawKey, ...rest] = pair.split('=');
    const key = decodeURIComponent(rawKey.replace(/\+/g, ' '));
    if (QUERY_KEYS.includes(key)) {
      params[key] = decodeURIComponent(rest.join('=').replace(/\+/g, ' '));
    }
  }
  return params;
}

export function resolve(path: string, query: string): Match | null {
  const normalized = path === '' ? '/' : path.replace(/\/+$/, '') || '/';
  const bare = normalized === '/' ? '' : normalized;
  for (const [routePath, view] of STATIC_VIEWS) {
    if (bare === routePath) return { view, params: parseQuery(query) };
  }
  // /movie/:imdbId and /tv/:showId detail routes.
  const detail = /^\/(movie|tv)\/([^/?]+)$/.exec(normalized);
  if (!detail) return null;
  const [, kind, id] = detail;
  const key = kind === 'movie' ? 'imdbId' : 'showId';
  return {
    view: kind === 'movie' ? 'movie' : 'tvshow',
    params: { ...parseQuery(query), [key]: decodeURIComponent(id) },
  };
}

export function pathFor(view: RouteView, params: Record<string, string> = {}): string {
  const base: Record<RouteView, string> = {
    discover: '/',
    movies: '/movies',
    tv: '/tv',
    search: '/search',
    movie: `/movie/${encodeURIComponent(params.imdbId ?? '')}`,
    tvshow: `/tv/${encodeURIComponent(params.showId ?? '')}`,
    library: '/library',
    monitored: '/monitored',
    queue: '/queue',
    settings: '/settings',
  };
  const query = QUERY_KEYS
    .filter((key) => params[key] !== undefined && params[key] !== '')
    .map((key) => `${key}=${encodeURIComponent(params[key])}`);
  return query.length ? `${base[view]}?${query.join('&')}` : base[view];
}

interface BrowserWindow {
  location: { pathname: string; search: string; href: string };
  history: {
    pushState: (state: Record<string, never>, title: string, target: string) => void;
    replaceState: (state: Record<string, never>, title: string, target: string) => void;
  };
  addEventListener: (type: string, handler: (event: { state?: unknown }) => void) => void;
  dispatchEvent: (event: Record<string, unknown>) => boolean;
  scrollTo?: (x: number, y: number) => void;
}

declare const globalThis: { window?: BrowserWindow };

const observedLocation = $state({ path: '/', search: '' });

function normalizePath(path: string): string {
  if (path === '') return '/';
  return path.startsWith('/') ? path : `/${path}`;
}

export function route(): Match | null {
  return resolve(observedLocation.path, observedLocation.search);
}

export function currentPath(): string {
  return observedLocation.path;
}

export function setLocation(path: string, search: string): void {
  observedLocation.path = normalizePath(path);
  observedLocation.search = search;
}

export function syncLocation(): void {
  const view = globalThis.window;
  if (!view) return;
  setLocation(view.location.pathname || '/', view.location.search);
}

export function navigate(to: string): void {
  const view = globalThis.window;
  if (view) {
    try {
      view.history.pushState({}, '', to);
    } catch {
      // Non-browser test environments may reject pushState.
    }
    const isJsdom = typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent);
    if (!isJsdom && typeof view.scrollTo === 'function') {
      try {
        view.scrollTo(0, 0);
      } catch {
        // Ignore non-browser scroll environments.
      }
    }
  }
  const [pathPart, queryPart] = to.split('?', 2);
  setLocation(pathPart, queryPart ?? '');
}

const observer = $state({ attachedTo: null as BrowserWindow | null });

export function observeHistory(): void {
  const view = globalThis.window;
  if (!view) return;
  if (observer.attachedTo === view) return;
  observer.attachedTo = view;
  view.addEventListener('popstate', () => syncLocation());
}
