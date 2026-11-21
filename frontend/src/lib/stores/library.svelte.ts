// Cached disk-library lookup: /library and the Ctrl+K palette both read this
// in-memory copy, so palette typing never hits the network.
import { api } from '../../lib/api';
import type { LibraryMovie, LibraryShow } from '../../lib/api';

interface Cache {
  movies: LibraryMovie[];
  shows: LibraryShow[];
  fetchedAt: number;
}

export interface LocalLibraryMatch {
  name: string;
  kind: 'movie' | 'tv';
  seeding: boolean;
  imdb_id?: string | null;
  tmdb_id?: number | null;
  year?: number | null;
}

const cache = $state({ cached: null as Cache | null });

export function isCached(): boolean {
  return cache.cached !== null;
}

export function movies(): LibraryMovie[] {
  return cache.cached?.movies ?? [];
}

export function shows(): LibraryShow[] {
  return cache.cached?.shows ?? [];
}

export function libraryCount(): number {
  return movies().length + shows().length;
}

export function seededTitles(): number {
  return [...movies(), ...shows()].filter((item) => item.seeding).length;
}

export async function refresh(): Promise<void> {
  const scanned = await api.library();
  cache.cached = {
    movies: scanned.movies,
    shows: scanned.shows,
    fetchedAt: Date.now(),
  };
}

export async function refreshIfStale(maxAgeMs = 10000): Promise<void> {
  const current = cache.cached;
  if (current && Date.now() - current.fetchedAt <= maxAgeMs) return;
  await refresh();
}

export function invalidate(): void {
  cache.cached = null;
}

export function localMatches(query: string, limit = 8): LocalLibraryMatch[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  const named: LocalLibraryMatch[] = [
    ...movies().map((item) => ({
      name: item.title,
      kind: 'movie' as const,
      seeding: item.seeding,
      imdb_id: item.imdb_id,
      year: item.year,
    })),
    ...shows().map((item) => ({
      name: item.title,
      kind: 'tv' as const,
      seeding: item.seeding,
      tmdb_id: item.tmdb_id,
      year: item.year,
    })),
  ];
  return named.filter((item) => item.name.toLowerCase().includes(needle)).slice(0, limit);
}

export function findMovie(imdbId: string): LibraryMovie | null {
  return movies().find((item) => item.imdb_id === imdbId) ?? null;
}

export function findShow(tmdbId: number): LibraryShow | null {
  return shows().find((item) => item.tmdb_id === tmdbId) ?? null;
}
