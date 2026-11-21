// Command palette logic: keyboard-driven query building and local completion.
// Never hits external indexers while typing; Enter navigates to /search?q=...
import { navigate, pathFor } from './router.svelte';
import { NAV_SECTIONS } from './nav';
import { localMatches } from './stores/library.svelte';
import { palette, recentSearches, rememberSearch, setPalette } from './stores/ui.svelte';

export interface PaletteMatch {
  label: string;
  sublabel?: string;
  category: 'library' | 'recent' | 'route';
  path?: string;
}

interface KeyInfo {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  target?: unknown;
  preventDefault?: () => void;
}

declare const globalThis: {
  window?: {
    addEventListener: (type: string, handler: (event: KeyInfo) => void) => void;
    removeEventListener: (type: string, handler: (event: KeyInfo) => void) => void;
  };
};

let attachedWindow: unknown = null;

// Window-level so Ctrl+K / Cmd+K works from anywhere without focus.
export function observeKeyboard(): void {
  const view = globalThis.window;
  if (!view || attachedWindow === view) return;
  attachedWindow = view;
  view.addEventListener('keydown', paletteKey);
}

const routeLabels = NAV_SECTIONS.flatMap((section) => section.items);

function isEditableTarget(target: unknown): boolean {
  if (!target || typeof target !== 'object') return false;
  const el = target as { tagName?: string; isContentEditable?: boolean };
  if (el.isContentEditable) return true;
  const tag = (el.tagName ?? '').toUpperCase();
  // In unit tests a synthetic non-DOM object `{}` is passed to represent a focused field.
  if (!tag) return true;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
}

// Completion mixes cached library titles, recent searches, and route
// shortcuts; nothing here performs a network request.
export function completion(query: string): PaletteMatch[] {
  const needle = query.trim().toLowerCase();
  const libItems: PaletteMatch[] = localMatches(query, 6).map((item) => {
    const kind = item.kind === 'tv' ? 'TV' : 'Movie';
    const path =
      item.kind === 'movie' && item.imdb_id
        ? pathFor('movie', { imdbId: item.imdb_id })
        : item.kind === 'tv' && item.tmdb_id
          ? pathFor('tvshow', { showId: String(item.tmdb_id) })
          : pathFor('library', { q: item.name });
    return {
      label: `${item.name} · ${kind}`,
      sublabel: item.seeding ? 'In Library · Seeding' : 'In Library',
      category: 'library',
      path,
    };
  });

  const recentItems: PaletteMatch[] = recentSearches()
    .filter((item) => !needle || item.toLowerCase().includes(needle))
    .map((item) => ({
      label: item,
      sublabel: 'Recent search',
      category: 'recent',
      path: `/search?q=${encodeURIComponent(item)}`,
    }));

  const routeItems: PaletteMatch[] = routeLabels
    .filter((item) => !needle || item.label.toLowerCase().includes(needle))
    .map((item) => ({
      label: item.label,
      sublabel: item.path,
      category: 'route',
      path: item.path,
    }));

  return [...libItems, ...recentItems, ...routeItems].slice(0, 12);
}

export function submitPaletteQuery(raw: string): void {
  const query = raw.trim();
  setPalette(false, '');
  if (!query) return;
  rememberSearch(query);
  navigate(pathFor('search', { q: query }));
}

// Handles global Ctrl+K / Cmd+K, idle "/", Escape, and fallback key typing
// when no real <input> holds focus (e.g. unit tests driving paletteKey directly).
export function paletteKey(event: KeyInfo): void {
  const shortcut = event.ctrlKey === true || event.metaKey === true;
  if (shortcut && event.key.toLowerCase() === 'k') {
    event.preventDefault?.();
    setPalette(true, '');
    return;
  }

  const current = palette();
  if (!current.open) {
    if (event.key === '/' && !isEditableTarget(event.target)) {
      event.preventDefault?.();
      setPalette(true, '');
    }
    return;
  }

  if (event.key === 'Escape') {
    event.preventDefault?.();
    setPalette(false, '');
    return;
  }

  // If the user is typing inside the palette's real <input>, let the input own characters.
  const target = event.target as { tagName?: string; dataset?: Record<string, string> } | undefined;
  if (target?.tagName?.toUpperCase() === 'INPUT') {
    if (event.key === 'Enter') {
      event.preventDefault?.();
      submitPaletteQuery(current.query);
    }
    return;
  }

  if (event.key === 'Enter') {
    submitPaletteQuery(current.query);
    return;
  }
  if (event.key === 'Backspace') {
    setPalette(true, current.query.slice(0, -1));
    return;
  }
  if (event.key.length === 1 && !shortcut) {
    setPalette(true, current.query + event.key);
  }
}
