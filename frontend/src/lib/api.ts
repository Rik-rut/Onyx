// Typed REST client for Onyx's FastAPI surface (src/arr/web/routes/*.py).
// Relative paths keep the SPA same-origin: production is served by FastAPI
// itself, development by scripts/dev-proxy.mjs.
interface Fetched {
  ok: boolean;
  status: number;
  statusText: string;
  text: () => Promise<string>;
}

interface FetchOptions {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
}

declare const globalThis: {
  fetch: (url: string, options?: FetchOptions) => Promise<Fetched>;
};

const BASE = '/api';
export const queueSocketUrl = '/ws/queue';

export const MOVIE_GENRES: readonly string[] = [
  'Action',
  'Adventure',
  'Animation',
  'Comedy',
  'Crime',
  'Drama',
  'Fantasy',
  'Horror',
  'Mystery',
  'Romance',
  'Sci-Fi',
  'Thriller',
];

export const TV_GENRES: readonly string[] = [
  'Action',
  'Adventure',
  'Animation',
  'Anime',
  'Comedy',
  'Crime',
  'Drama',
  'Fantasy',
  'Horror',
  'Mystery',
  'Romance',
  'Sci-Fi',
  'Thriller',
];

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly path: string;

  constructor(status: number, detail: string, path: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
    this.path = path;
  }
}

export const isDuplicateDownload = (error: unknown): boolean =>
  error instanceof ApiError && error.status === 409;

function buildQuery(values: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === null || value === '') continue;
    parts.push(`${key}=${encodeURIComponent(String(value))}`);
  }
  return parts.length ? `?${parts.join('&')}` : '';
}

async function request(method: string, path: string, body?: unknown): Promise<unknown> {
  const options: FetchOptions = { method };
  if (body !== undefined) {
    options.headers = { 'content-type': 'application/json' };
    options.body = JSON.stringify(body);
  }
  let response: Fetched;
  try {
    response = await globalThis.fetch(path, options);
  } catch (failure) {
    throw new ApiError(0, `backend unreachable: ${String(failure)}`, path);
  }
  const payload = await response.text();
  if (response.ok) return payload === '' ? null : JSON.parse(payload);
  let detail = response.statusText;
  try {
    const parsed = JSON.parse(payload);
    if (parsed && typeof parsed.detail === 'string') detail = parsed.detail;
  } catch (parseFailure) {
    void parseFailure;
  }
  throw new ApiError(response.status, detail, path);
}

export interface MediaItem {
  id?: string | number;
  imdb_id?: string;
  tmdb_id?: number;
  title?: string;
  name?: string;
  year?: number | null;
  rating?: number | string | null;
  genres?: string[];
  poster?: string;
  overview?: string;
  in_library?: boolean;
  library_status?: 'available' | 'partial' | 'monitored' | 'queued' | null;
  available_seasons?: Record<string, number[]>;
  monitored?: boolean;
}

export interface DiscoverPayload {
  spotlight: MediaItem | null;
  trending_movies: MediaItem[];
  trending_tv: MediaItem[];
  top_rated_movies: MediaItem[];
  genres: string[];
  genres_by_type: Record<string, string[]>;
}

export interface BrowsePayload {
  media_type: 'movie' | 'tv';
  genre: string;
  page: number;
  has_more: boolean;
  items: MediaItem[];
}

export interface ReleaseItem {
  indexer: string;
  title: string;
  infohash: string;
  magnet: string;
  seeds: number;
  peers: number;
  size_bytes: number;
  resolution?: string | null;
  codec?: string | null;
  source?: string | null;
  score: number;
  is_pack: boolean;
  /** Original indexer torrent name, kept for the drawer's coverage display. */
  raw_title?: string | null;
  /** Parsed season number, when the release names one. */
  season?: number | null;
  /** Parsed episode number, when the release names one. */
  episode?: number | null;
  /** Seasons covered by a pack (list-typed season from the release name). */
  seasons?: number[] | null;
  /** Pre-computed coverage label: "S02", "S02E05", or a range like "S01-S05". */
  season_label?: string | null;
  reasons?: string[];
}

export interface QueueItem {
  id: number | string;
  infohash: string;
  name: string;
  progress: number;
  status_code: number;
  status: string;
  rate_download: number;
  rate_upload: number;
  eta: number;
  total_size: number;
  media_type?: string | null;
}

export interface LibraryMovie {
  name: string;
  title: string;
  year: number | null;
  path: string;
  file_count: number;
  size_mb: number;
  primary_ext: string;
  imdb_id: string | null;
  seeding: boolean;
  poster: string;
}

export interface LibraryShow {
  name: string;
  title: string;
  year: number | null;
  path: string;
  seasons_count: number;
  episodes_count: number;
  monitored_count: number;
  missing: number[];
  monitored: boolean;
  monitored_id: number | null;
  tmdb_id: number | null;
  seeding: boolean;
  poster: string;
}

export interface LibraryPayload {
  movies: LibraryMovie[];
  shows: LibraryShow[];
  sync: Record<string, unknown>;
}

export interface SeriesRow {
  id: number;
  tmdb_id: number;
  imdb_id: string | null;
  title: string;
  status: string | null;
  quality: string | null;
  total_episodes: number;
  imported_episodes: number;
  missing_episodes: number;
}

export interface MovieDetails {
  id: string;
  imdb_id: string;
  title: string;
  year: number | null;
  overview: string;
  rating: number | null;
  genres: string[];
  runtime: number | null;
  poster: string;
  stars: string[];
  similar: MediaItem[];
  degraded: boolean;
  in_library: boolean;
  library_status: 'available' | 'partial' | 'monitored' | 'queued' | null;
}

export interface TvDetails {
  id: number;
  title: string;
  year: number | null;
  imdb_id: string | null;
  tvdb_id: string | null;
  status: string | null;
  seasons: Array<{ season_number: number; episodes: Array<Record<string, unknown>> }>;
  in_library: boolean;
  library_status: 'available' | 'partial' | 'monitored' | 'queued' | null;
  monitored: boolean;
  available_seasons: Record<string, number[]>;
  overview: string;
  rating: number | null;
  genres: string[];
  poster: string;
  network: string;
  similar: MediaItem[];
}

export interface ConfigValues {
  download_root: string;
  library_root: string;
  import_mode: string;
  max_concurrent_downloads: number;
  prefer_season_packs: boolean;
  seeding_policy: string;
  resolutions: string[];
  subtitle_languages: string[];
  subtitles_enabled: boolean;
  subtitles_forced_only: boolean;
  max_download_speed_kbps: number | null;
  max_upload_speed_kbps: number | null;
}

const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

export function formatBytes(bytes: number): string {
  let value = Math.max(0, Math.floor(bytes));
  let unit = 0;
  while (value >= 1000 && unit < BYTE_UNITS.length - 1) {
    value = Math.floor((value / 1000) * 10) / 10;
    unit += 1;
  }
  const rounded = unit === 0 ? `${value}` : value.toFixed(value < 10 ? 1 : 0);
  return `${rounded} ${BYTE_UNITS[unit]}`;
}

export function formatSpeed(bytesPerSecond: number): string {
  return `${formatBytes(bytesPerSecond)}/s`;
}

export function formatEta(seconds: number): string {
  if (seconds < 0) return '—';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = Math.floor(seconds % 60);
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, '0')}m`;
  if (minutes > 0) return `${minutes}m ${String(rest).padStart(2, '0')}s`;
  return `${rest}s`;
}

export const BADGE_LABELS: Record<string, string> = {
  available: 'In Library',
  partial: 'Partially Available',
  queued: 'In Queue',
  monitored: 'Monitoring',
};

export const libraryBadgeLabel = (status: string | null | undefined): string | null =>
  BADGE_LABELS[status ?? ''] ?? null;

export function libraryBadgeTone(status: string | null | undefined): string {
  switch (status) {
    case 'available':
      return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/35';
    case 'partial':
      return 'bg-amber-500/20 text-amber-300 border-amber-500/35';
    case 'queued':
      return 'bg-sky-500/20 text-sky-300 border-sky-500/35';
    case 'monitored':
      return 'bg-indigo-500/20 text-indigo-200 border-indigo-400/35';
    default:
      return 'bg-slate-800/80 text-slate-300 border-slate-700';
  }
}

export const releaseResolutionChip = (release: ReleaseItem): string | null => {
  const value = `${release.resolution ?? ''} ${release.title}`.toLowerCase();
  if (/2160|4k|uhd/.test(value)) return '4K / 2160p';
  if (/1080/.test(value)) return '1080p';
  if (/720/.test(value)) return '720p';
  return null;
};

export function filterReleases(items: ReleaseItem[], chip: string): ReleaseItem[] {
  if (chip === 'All') return [...items];
  return items.filter((item) => releaseResolutionChip(item) === chip);
}

export function sortReleases(items: ReleaseItem[], mode: 'score' | 'seeds' | 'size'): ReleaseItem[] {
  const ordered = [...items];
  if (mode === 'seeds') ordered.sort((a, b) => b.seeds - a.seeds);
  else if (mode === 'size') ordered.sort((a, b) => a.size_bytes - b.size_bytes);
  else ordered.sort((a, b) => b.score - a.score || b.seeds - a.seeds);
  return ordered;
}

// "Download Best": highest backend score, breaking ties by seeders.
export const bestRelease = (items: ReleaseItem[]): ReleaseItem | null =>
  items.reduce((best: ReleaseItem | null, item) => {
    if (!best) return item;
    if (item.score > best.score || (item.score === best.score && item.seeds > best.seeds)) return item;
    return best;
  }, null);

export const api = {
  async discover(): Promise<DiscoverPayload> {
    return (await request('GET', `${BASE}/discover`)) as DiscoverPayload;
  },

  async browse(mediaType: 'movie' | 'tv', genre?: string, page = 1): Promise<BrowsePayload> {
    return (await request('GET', `${BASE}/discover/browse${buildQuery({ media_type: mediaType, genre, page })}`)) as BrowsePayload;
  },

  async genreBrowse(genre: string, mediaType: 'movie' | 'tv'): Promise<Record<string, unknown>> {
    return (await request('GET', `${BASE}/discover/genre${buildQuery({ genre, media_type: mediaType })}`)) as Record<string, unknown>;
  },

  async searchMovies(q: string): Promise<MediaItem[]> {
    return (await request('GET', `${BASE}/search/movies${buildQuery({ q })}`)) as MediaItem[];
  },

  async searchTv(q: string): Promise<MediaItem[]> {
    return (await request('GET', `${BASE}/search/tv${buildQuery({ q })}`)) as MediaItem[];
  },

  async movieDetails(imdbId: string): Promise<MovieDetails> {
    return (await request('GET', `${BASE}/movie/${encodeURIComponent(imdbId)}/details`)) as MovieDetails;
  },

  async tvDetails(showId: number): Promise<TvDetails> {
    return (await request('GET', `${BASE}/tv/${showId}/details`)) as TvDetails;
  },

  async releasesMovie(title: string, year?: number, imdbId?: string): Promise<ReleaseItem[]> {
    return (await request('GET', `${BASE}/releases/movie${buildQuery({ title, year, imdb_id: imdbId })}`)) as ReleaseItem[];
  },

  async releasesTv(title: string, season?: number, episode?: number, pack = false): Promise<ReleaseItem[]> {
    return (await request('GET', `${BASE}/releases/tv${buildQuery({ title, season, episode, pack })}`)) as ReleaseItem[];
  },

  async downloadRelease(release: ReleaseItem, target: Record<string, unknown>, force = false): Promise<Record<string, unknown>> {
    return (await request('POST', `${BASE}/queue/download/release`, { ...release, ...target, force })) as Record<string, unknown>;
  },

  async downloadMagnet(magnet: string): Promise<Record<string, unknown>> {
    return (await request('POST', `${BASE}/queue/download/magnet`, { magnet })) as Record<string, unknown>;
  },

  async importNow(): Promise<Record<string, unknown>> {
    return (await request('POST', `${BASE}/queue/import`)) as Record<string, unknown>;
  },

  async queue(): Promise<QueueItem[]> {
    return (await request('GET', `${BASE}/queue`)) as QueueItem[];
  },

  async queueAction(id: number | string, action: string): Promise<Record<string, unknown>> {
    // Normalize legacy underscore names to the actual FastAPI paths (/priority/up, /priority/down).
    const normalized =
      action === 'priority_up'
        ? 'priority/up'
        : action === 'priority_down'
          ? 'priority/down'
          : action;
    return (await request('POST', `${BASE}/queue/${encodeURIComponent(String(id))}/${normalized}`)) as Record<string, unknown>;
  },

  async removeTorrent(id: number | string, confirm: boolean): Promise<Record<string, unknown>> {
    return (await request('POST', `${BASE}/queue/${encodeURIComponent(String(id))}/delete`, { confirm })) as Record<string, unknown>;
  },

  async library(): Promise<LibraryPayload> {
    return (await request('GET', `${BASE}/library`)) as LibraryPayload;
  },

  async libraryAction(action: string, kind: 'movie' | 'tv', name: string, confirm = false): Promise<Record<string, unknown>> {
    return (await request('POST', `${BASE}/library/${action}`, { kind, name, confirm })) as Record<string, unknown>;
  },

  async series(): Promise<SeriesRow[]> {
    return (await request('GET', `${BASE}/series`)) as SeriesRow[];
  },

  async monitorSeries(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return (await request('POST', `${BASE}/series/monitor`, payload)) as Record<string, unknown>;
  },

  async unmonitorSeries(seriesId: number): Promise<Record<string, unknown>> {
    return (await request('DELETE', `${BASE}/series/${seriesId}`)) as Record<string, unknown>;
  },

  async config(): Promise<ConfigValues> {
    return (await request('GET', `${BASE}/config`)) as ConfigValues;
  },

  async saveConfig(values: Record<string, unknown>): Promise<ConfigValues> {
    const res = (await request('PUT', `${BASE}/config`, values)) as ConfigValues | { status?: string; config?: ConfigValues };
    if (res && typeof res === 'object' && 'config' in res && res.config) {
      return res.config;
    }
    return res as ConfigValues;
  },
};
