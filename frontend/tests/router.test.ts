import { expect, test } from 'vitest';
import { currentPath, navigate, observeHistory, pathFor, resolve, route, setLocation, syncLocation } from '../src/lib/router.svelte';

test('static views resolve from the history path', () => {
  expect(resolve('/', '').view).toBe('discover');
  expect(resolve('/movies', '').view).toBe('movies');
  expect(resolve('/tv/', '').view).toBe('tv');
  expect(resolve('/queue', '').view).toBe('queue');
  expect(resolve('/settings', '').view).toBe('settings');
});

test('unknown client paths fall through to the shell default', () => {
  expect(resolve('/api/queue', '')).toBe(null);
  expect(resolve('/nope/', '')).toBe(null);
});

test('detail routes extract typed params', () => {
  const movie = resolve('/movie/tt1375666', '');
  expect(movie.view).toBe('movie');
  expect(movie.params.imdbId).toBe('tt1375666');
  const show = resolve('/tv/456', '?q=breaking+bad');
  expect(show.view).toBe('tvshow');
  expect(show.params.showId).toBe('456');
  expect(show.params.q).toBe('breaking bad');
});

test('query parsing keeps only q and genre', () => {
  const matched = resolve('/search', '?q=the%20lake&genre=Comedy&csrf=abc');
  expect(matched.view).toBe('search');
  expect(matched.params).toEqual({ q: 'the lake', genre: 'Comedy' });
});

test('pathFor round-trips through resolve', () => {
  for (const [view, params] of [
    ['discover', {}],
    ['queue', {}],
    ['search', { q: 'the lake' }],
    ['tv', { genre: 'Drama' }],
    ['movie', { imdbId: 'tt1375666' }],
    ['tvshow', { showId: '456' }],
  ]) {
    const path = pathFor(view, params);
    const [bare, query] = path.split('?', 2);
    const matched = resolve(bare, query ?? '');
    expect(matched.view).toBe(view);
    for (const [key, value] of Object.entries(params)) {
      expect(matched.params[key]).toBe(value);
    }
  }
});

// The History API surface is injected so the assertions cover the wiring
// (pushState target, popstate handler) rather than a browser engine.
declare const globalThis: {
  window?: {
    location: { pathname: string; search: string };
    history: {
      pushState: (state: Record<string, never>, title: string, target: string) => void;
      replaceState: (url: string, title: string) => void;
    };
    addEventListener: (type: string, handler: (event: { state?: unknown }) => void) => void;
    dispatchEvent: (event: Record<string, unknown>) => boolean;
    scrollTo: (x: number, y: number) => void;
  };
};

const attached = new Map<string, (event: { state?: unknown }) => void>();
const pushed: string[] = [];
const browserLocation = { pathname: '/movies', search: '?genre=Drama' };

function installWindow(): void {
  globalThis.window = {
    location: browserLocation,
    history: {
      pushState: (_state, _title, target) => void pushed.push(target),
      replaceState: (url, _title) => void (browserLocation.pathname = url),
    },
    addEventListener: (type, handler) => void attached.set(type, handler),
    dispatchEvent: () => true,
    scrollTo: () => {},
  };
}

test('navigate pushes the previous route onto history', () => {
  installWindow();
  setLocation('/movie/tt1375666', '');
  expect(route()?.view).toBe('movie');
  navigate('/queue');
  expect(pushed).toEqual(['/queue']);
  expect(currentPath()).toBe('/queue');
  expect(route()?.view).toBe('queue');
});

test('popstate reloads resync the reactive location', () => {
  installWindow();
  observeHistory();
  expect(attached.has('popstate')).toBe(true);
  syncLocation();
  expect(route()?.view).toBe('movies');
  expect(route()?.params.genre).toBe('Drama');
  // A hard reload moves the browser location, then fires popstate on the
  // re-parsed document; the listener republishes it reactively.
  browserLocation.pathname = '/monitored';
  browserLocation.search = '';
  (attached.get('popstate'))?.({});
  expect(route()?.view).toBe('monitored');
});
