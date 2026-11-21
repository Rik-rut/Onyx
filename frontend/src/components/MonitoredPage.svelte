<!-- /monitored: tracked TV series cards with cached artwork fallback, episode
     completion progress bars, missing episode pills, click-through to /tv/:id,
     and confirmed Unmonitor action. -->
<script lang="ts">
  import { api, ApiError } from '../lib/api';
  import type { SeriesRow } from '../lib/api';
  import { movies, shows } from '../lib/stores/library.svelte';
  import { navigate } from '../lib/router.svelte';
  import { askConfirmation, pushToast } from '../lib/stores/ui.svelte';

  interface CardRow {
    seriesId: number;
    tmdbId: number;
    title: string;
    status: string;
    quality: string;
    imported: number;
    total: number;
    missing: number;
    percent: number;
    poster: string;
    initials: string;
    open: () => void;
    onKey: (event: KeyboardEvent) => void;
    unmonitorClick: (event: MouseEvent) => void;
  }

  const box = $state({
    loading: null as null | Promise<void>,
    abandoned: false,
    loaded: false,
    series: [] as SeriesRow[],
    error: null as string | null,
    actionError: null as string | null,
    brokenPosters: {} as Record<number, boolean>,
  });

  $effect(() => ensureLoaded());

  function ensureLoaded(): void {
    if (box.loading === null && !box.loaded && !box.abandoned) {
      box.loading = load();
    }
  }

  function failureText(failure: unknown): string {
    return failure instanceof ApiError ? failure.detail : String(failure);
  }

  async function load(): Promise<void> {
    try {
      box.series = await api.series();
      box.loaded = true;
      box.error = null;
      box.abandoned = false;
    } catch (failure) {
      box.error = failureText(failure);
      box.abandoned = true;
    }
    box.loading = null;
  }

  function retry(): void {
    box.abandoned = false;
    box.loading = null;
    ensureLoaded();
  }

  function posterFor(row: SeriesRow): string {
    const title = row.title.trim().toLowerCase();
    const show =
      shows().find((item) => item.tmdb_id === row.tmdb_id) ??
      shows().find((item) => item.title.trim().toLowerCase() === title);
    if (show?.poster) return show.poster;
    const movie = movies().find((item) => item.title.trim().toLowerCase() === title);
    return movie?.poster ?? '';
  }

  function initialsOf(title: string): string {
    return title
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0]?.toUpperCase() ?? '')
      .join('');
  }

  function percentOf(imported: number, total: number): number {
    if (total <= 0) return 0;
    return Math.max(0, Math.min(100, Math.round((imported / total) * 100)));
  }

  function openShow(tmdbId: number): void {
    if (!Number.isFinite(tmdbId) || tmdbId <= 0) return;
    navigate(`/tv/${tmdbId}`);
  }

  function onCardKey(event: KeyboardEvent, tmdbId: number): void {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    openShow(tmdbId);
  }

  async function unmonitor(row: SeriesRow): Promise<void> {
    const approved = await askConfirmation({
      id: `unmonitor-${row.id}`,
      title: 'Unmonitor show',
      message: `Stop monitoring ${row.title}?`,
      kind: 'danger',
      confirmLabel: 'Unmonitor',
    });
    if (!approved) return;
    try {
      await api.unmonitorSeries(row.id);
    } catch (failure) {
      box.actionError = failureText(failure);
      return;
    }
    box.actionError = null;
    box.series = box.series.filter((item) => item.id !== row.id);
    pushToast({ message: `Stopped monitoring ${row.title}`, kind: 'info' });
  }

  function cardRows(): CardRow[] {
    return box.series.map((row) => {
      const imported = Math.max(0, Number(row.imported_episodes) || 0);
      const total = Math.max(0, Number(row.total_episodes) || 0);
      return {
        seriesId: row.id,
        tmdbId: row.tmdb_id,
        title: row.title,
        status: row.status ?? 'Monitored',
        quality: row.quality ?? 'Auto',
        imported,
        total,
        missing: Math.max(0, total - imported),
        percent: percentOf(imported, total),
        poster: posterFor(row),
        initials: initialsOf(row.title),
        open: () => openShow(row.tmdb_id),
        onKey: (event: KeyboardEvent) => onCardKey(event, row.tmdb_id),
        unmonitorClick: (event: MouseEvent) => {
          event.stopPropagation();
          void unmonitor(row);
        },
      };
    });
  }

  const rows = $derived(cardRows());
</script>

<div class="flex flex-col gap-6" data-testid="monitored-page">
  <header class="flex flex-wrap items-center justify-between gap-4">
    <div>
      <h1 class="text-2xl sm:text-3xl font-black text-white tracking-tight">Monitored Series</h1>
      <p class="mt-1 text-xs sm:text-sm text-slate-400">
        TV shows automatically tracked for new and missing episodes
      </p>
    </div>
    <button
      type="button"
      class="rounded-xl px-4 py-2 bg-onyx-surface hover:bg-onyx-raised border border-onyx-border text-xs font-semibold text-slate-200 hover:text-white transition-colors cursor-pointer"
      onclick={() => {
        box.loaded = false;
        retry();
      }}
    >
      Refresh
    </button>
  </header>

  {#if box.actionError}
    <div
      class="rounded-xl px-4 py-3 bg-rose-950/40 border border-rose-800/50 text-rose-300 text-xs sm:text-sm"
      data-testid="monitored-action-error"
      role="status"
    >
      {box.actionError}
    </div>
  {/if}

  {#if box.error && !box.loaded}
    <div
      class="rounded-2xl p-6 bg-onyx-surface border border-amber-700/40 flex flex-wrap items-center justify-between gap-4"
      data-testid="monitored-error"
      role="status"
      aria-live="polite"
    >
      <div class="space-y-1">
        <p class="text-sm font-semibold text-amber-300">Could not load monitored series</p>
        <p class="text-xs text-slate-400" data-testid="monitored-error-message">{box.error}</p>
      </div>
      <button
        class="rounded-xl px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold cursor-pointer"
        type="button"
        data-testid="monitored-retry"
        onclick={() => retry()}
      >
        Retry now
      </button>
    </div>
  {:else if !box.loaded}
    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4 sm:gap-5" data-testid="monitored-loading" aria-live="polite">
      <span class="sr-only">Loading monitored shows…</span>
      {#each [0, 1, 2, 3, 4] as _}
        <div class="rounded-2xl overflow-hidden border border-onyx-border/60 bg-onyx-surface p-3 space-y-3">
          <div class="aspect-[2/3] rounded-xl skeleton-pulse"></div>
          <div class="h-4 w-3/4 rounded skeleton-pulse"></div>
          <div class="h-2 w-full rounded skeleton-pulse"></div>
        </div>
      {/each}
    </div>
  {:else if rows.length === 0}
    <div
      class="rounded-2xl py-16 px-6 bg-onyx-surface/70 border border-onyx-border text-center space-y-3"
      data-testid="no-results"
      role="status"
      aria-live="polite"
    >
      <p class="text-sm font-medium text-slate-300">No monitored shows yet.</p>
      <p class="text-xs text-slate-500 max-w-md mx-auto">
        Open any TV show from Discover, TV Shows, or Search and click <strong class="text-slate-300">+ Monitor</strong> to track new episodes automatically.
      </p>
      <button
        type="button"
        class="mt-1 rounded-xl px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold cursor-pointer"
        onclick={() => navigate('/tv')}
      >
        Browse TV Shows
      </button>
    </div>
  {:else}
    <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 sm:gap-5" data-testid="monitored-grid">
      {#each rows as row (row.seriesId)}
        {@const showPoster = Boolean(row.poster) && !box.brokenPosters[row.seriesId]}
        <div
          class="group rounded-2xl overflow-hidden bg-onyx-surface border border-onyx-border/80 hover:border-indigo-500/80 shadow-md shadow-black/40 transition-colors cursor-pointer flex flex-col"
          data-testid="monitored-card"
          data-series-id={row.seriesId}
          data-tmdb-id={row.tmdbId}
          role="button"
          tabindex="0"
          aria-label={`Open ${row.title}`}
          onclick={row.open}
          onkeydown={row.onKey}
        >
          <!-- Artwork Banner -->
          <div class="relative h-44 w-full bg-onyx-raised overflow-hidden">
            {#if showPoster}
              <img
                class="w-full h-full object-cover poster-zoom"
                data-testid="card-poster"
                src={row.poster}
                alt={`${row.title} poster`}
                onerror={() => (box.brokenPosters = { ...box.brokenPosters, [row.seriesId]: true })}
              />
            {:else}
              <div
                class="w-full h-full bg-gradient-to-br from-slate-800 via-onyx-surface to-indigo-950/70 flex items-center justify-center"
                data-testid="card-poster-fallback"
                role="img"
                aria-label={`No artwork for ${row.title}`}
              >
                <span class="text-3xl font-black tracking-wider text-slate-500/80" data-testid="card-poster-initials">
                  {row.initials}
                </span>
              </div>
            {/if}

            <div class="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-onyx-surface via-onyx-surface/60 to-transparent"></div>

            <span class="absolute top-2.5 left-2.5 rounded-md bg-black/75 backdrop-blur-sm border border-white/10 px-2 py-0.5 text-[10px] font-semibold text-indigo-300">
              {row.status}
            </span>

            <span
              class="absolute top-2.5 right-2.5 rounded-md bg-black/75 backdrop-blur-sm border border-white/10 px-2 py-0.5 text-[10px] font-mono font-semibold text-slate-300"
              data-testid="show-quality"
            >
              {row.quality}
            </span>
          </div>

          <!-- Progress & Controls -->
          <div class="p-4 flex-1 flex flex-col justify-between gap-4">
            <div class="space-y-3">
              <h2 class="text-sm sm:text-base font-bold text-white group-hover:text-indigo-300 transition-colors truncate" data-testid="card-title">
                {row.title}
              </h2>

              <div class="space-y-1.5">
                <div class="flex items-center justify-between text-xs">
                  <span class="font-mono text-slate-300" data-testid="episode-progress-text">
                    {row.imported} / {row.total}
                  </span>
                  <span class="font-mono text-slate-500">{row.percent}%</span>
                </div>
                <div
                  class="relative h-2 w-full rounded-full bg-onyx-obsidian overflow-hidden border border-onyx-border/60"
                  data-testid="episode-progress"
                  role="progressbar"
                  aria-label={`${row.title} episode progress`}
                  aria-valuemin="0"
                  aria-valuemax={row.total}
                  aria-valuenow={row.imported}
                >
                  <div
                    class="block h-full rounded-full transition-[width] duration-300 {row.percent === 100
                      ? 'bg-emerald-500'
                      : 'bg-indigo-500'}"
                    data-testid="episode-progress-fill"
                    style={`width: ${row.percent}%`}
                  ></div>
                </div>
              </div>
            </div>

            <div class="flex items-center justify-between gap-2 pt-3 border-t border-onyx-border/60">
              {#if row.total > row.imported}
                <span
                  class="inline-flex items-center rounded-md bg-amber-500/15 border border-amber-500/35 px-2 py-0.5 text-[11px] font-semibold text-amber-300"
                  data-testid="missing-badge"
                >
                  {row.missing} missing
                </span>
              {:else}
                <span class="inline-flex items-center rounded-md bg-emerald-500/15 border border-emerald-500/35 px-2 py-0.5 text-[11px] font-semibold text-emerald-300">
                  Complete
                </span>
              {/if}

              <button
                class="rounded-lg px-3 py-1 bg-rose-500/10 hover:bg-rose-600 border border-rose-500/35 text-rose-300 hover:text-white text-xs font-semibold transition-colors cursor-pointer"
                type="button"
                data-testid="unmonitor-button"
                aria-label={`Unmonitor ${row.title}`}
                onclick={row.unmonitorClick}
              >
                Unmonitor
              </button>
            </div>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
