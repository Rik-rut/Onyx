<!-- Movie detail view (/movie/:imdbId): cinematic hero backdrop, portrait 2:3
     poster, metadata pills, 1-click Download Best, Choose Release slide-over
     drawer, and horizontally scrollable More Like This rail. -->
<script lang="ts">
  import { api, ApiError, bestRelease, isDuplicateDownload, libraryBadgeLabel, libraryBadgeTone } from '../lib/api';
  import type { MovieDetails, ReleaseItem } from '../lib/api';
  import { route } from '../lib/router.svelte';
  import { askConfirmation, closeDrawer, drawer, openDrawer, pushToast, setDrawerReleases } from '../lib/stores/ui.svelte';
  import { findMovie } from '../lib/stores/library.svelte';
  import MediaRail from './MediaRail.svelte';
  import ReleaseDrawer from './ReleaseDrawer.svelte';

  const match = $derived(route());
  const viewId = $derived(match?.view === 'movie' ? match.params.imdbId ?? '' : '');

  const page = $state({
    details: null as MovieDetails | null,
    error: null as string | null,
    pending: false,
    firedFor: '',
    releases: null as ReleaseItem[] | null,
    downloadingBest: false,
    posterBroken: false,
  });

  function detailText(failure: unknown): string {
    if (failure instanceof ApiError) return failure.detail;
    return String(failure);
  }

  async function fetchDetails(id: string): Promise<void> {
    try {
      const fetched = await api.movieDetails(id);
      if (page.firedFor !== id) return;
      page.details = fetched;
      page.error = null;
    } catch (failure) {
      if (page.firedFor !== id) return;
      page.details = null;
      page.error = `Details unavailable: ${detailText(failure)}`;
    } finally {
      if (page.firedFor === id) page.pending = false;
    }
  }

  // Re-fetch and clear cached releases whenever navigating to a different movie.
  $effect(() => {
    const id = viewId;
    if (!id) return;
    if (page.firedFor !== id) {
      page.firedFor = id;
      page.details = null;
      page.error = null;
      page.releases = null;
      page.posterBroken = false;
      page.pending = true;
      closeDrawer();
      void fetchDetails(id);
    } else if (!page.pending && !page.details && !page.error) {
      page.pending = true;
      void fetchDetails(id);
    }
  });

  async function loadReleases(): Promise<ReleaseItem[]> {
    const details = page.details;
    if (!details) return [];
    if (page.releases) return page.releases;
    const fetched = await api.releasesMovie(details.title, details.year ?? undefined, details.imdb_id);
    page.releases = fetched;
    return fetched;
  }

  async function submitRelease(row: ReleaseItem, target: Record<string, unknown>): Promise<void> {
    try {
      await api.downloadRelease(row, target, false);
      pushToast({
        message: `Queued ${row.title}`,
        kind: 'success',
        actionLabel: 'Open queue',
        actionPath: '/queue',
      });
    } catch (failure) {
      if (!isDuplicateDownload(failure)) {
        pushToast({ message: `Could not queue ${row.title}: ${detailText(failure)}`, kind: 'error' });
        return;
      }
      const approved = await askConfirmation({
        id: `movie-${row.infohash}`,
        title: 'Already in library',
        message: `"${row.title}" is already in the library. Download it again?`,
        kind: 'duplicate',
        confirmLabel: 'Download again',
      });
      if (!approved) return;
      await api.downloadRelease(row, target, true);
      pushToast({
        message: `Queued ${row.title} again`,
        kind: 'success',
        actionLabel: 'Open queue',
        actionPath: '/queue',
      });
    }
  }

  async function downloadBest(): Promise<void> {
    const details = page.details;
    if (!details || page.downloadingBest) return;
    page.downloadingBest = true;
    try {
      const releases = await loadReleases();
      const best = bestRelease(releases);
      if (!best) {
        pushToast({ message: 'No matching releases found', kind: 'info' });
        return;
      }
      await submitRelease(best, {
        media_type: 'movie',
        imdb_id: details.imdb_id,
        year: details.year,
        display_title: details.title,
      });
    } catch (failure) {
      pushToast({ message: `Releases unavailable: ${detailText(failure)}`, kind: 'error' });
    } finally {
      page.downloadingBest = false;
    }
  }

  function chooseRelease(): void {
    const details = page.details;
    if (!details) return;
    openDrawer(
      'movie',
      {
        media_type: 'movie',
        imdb_id: details.imdb_id,
        year: details.year,
        display_title: details.title,
        title: details.title,
      },
      true,
    );
    void (async () => {
      try {
        setDrawerReleases(await loadReleases(), false);
      } catch {
        setDrawerReleases([], false);
      }
    })();
  }

  const details = $derived(page.details);
  const onDisk = $derived(findMovie(viewId));
  const statusKey = $derived(onDisk ? 'available' : details?.library_status ?? null);
  const badgeLabel = $derived(libraryBadgeLabel(statusKey));
  const drawerState = $derived(drawer());
  const drawerItems = $derived(
    drawerState?.open && drawerState.scope === 'movie'
      ? (drawerState.releases as ReleaseItem[])
      : null,
  );
</script>

<div
  class="flex flex-col gap-8"
  data-testid="movie-detail-page"
  data-view="movie"
  data-imdb={details?.imdb_id ?? ''}
>
  {#if page.error}
    <div
      class="rounded-2xl p-6 bg-onyx-surface border border-amber-700/40 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4"
      role="status"
      aria-live="polite"
      data-testid="movie-error"
    >
      <div class="space-y-1">
        <p class="text-sm font-semibold text-amber-300">Could not load movie details</p>
        <p class="text-xs text-slate-400" data-testid="movie-error-message">{page.error}</p>
      </div>
      <button
        class="rounded-xl px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold cursor-pointer"
        type="button"
        data-testid="movie-retry"
        onclick={() => {
          page.error = null;
          page.pending = false;
        }}
      >
        Retry
      </button>
    </div>
  {:else if details}
    <!-- Cinematic Hero Section -->
    <section
      class="relative overflow-hidden rounded-2xl border border-onyx-border/80 bg-onyx-surface shadow-xl shadow-black/40"
      data-testid="movie-backdrop"
      aria-label="Backdrop"
    >
      {#if details.poster && !page.posterBroken}
        <img
          class="absolute inset-0 w-full h-full object-cover opacity-20 blur-2xl scale-110 pointer-events-none"
          src={details.poster}
          alt=""
          data-testid="movie-backdrop-image"
        />
      {/if}
      <div class="absolute inset-0 bg-gradient-to-r from-onyx-obsidian via-onyx-obsidian/92 to-onyx-obsidian/60 pointer-events-none"></div>

      <div class="relative p-5 sm:p-8 flex flex-col md:flex-row gap-6 lg:gap-8">
        <!-- Portrait 2:3 Poster -->
        <div class="w-40 sm:w-48 md:w-52 shrink-0 aspect-[2/3] rounded-xl overflow-hidden bg-onyx-raised border border-white/10 shadow-2xl shadow-black/70">
          {#if details.poster && !page.posterBroken}
            <img
              class="w-full h-full object-cover"
              src={details.poster}
              alt={`Poster for ${details.title}`}
              data-testid="movie-poster"
              onerror={() => (page.posterBroken = true)}
            />
          {:else}
            <div class="w-full h-full bg-gradient-to-br from-slate-800 to-indigo-950/60 flex items-center justify-center p-4 text-center">
              <span class="text-2xl font-black text-slate-400">{(details.title || 'M').slice(0, 2).toUpperCase()}</span>
            </div>
          {/if}
        </div>

        <!-- Metadata + Actions -->
        <div class="flex-1 min-w-0 flex flex-col justify-between gap-5" data-testid="movie-metadata">
          <div class="space-y-3.5">
            <div class="flex flex-wrap items-center gap-2" data-testid="movie-facts">
              {#if details.rating}
                <span class="rounded-md bg-amber-500/15 border border-amber-500/30 px-2 py-0.5 text-xs font-bold text-amber-300" data-testid="movie-rating">
                  ★ {details.rating}
                </span>
              {/if}
              {#if details.year}
                <span class="text-xs font-mono text-slate-300" data-testid="movie-year">{details.year}</span>
              {/if}
              {#if details.runtime}
                <span class="text-xs font-mono text-slate-400" data-testid="movie-runtime">{details.runtime}m</span>
              {/if}
              {#if details.genres?.length}
                <span class="text-xs text-slate-400" data-testid="movie-genres">{details.genres.join(', ')}</span>
              {/if}
            </div>

            <h1 class="text-2xl sm:text-3xl lg:text-4xl font-black text-white tracking-tight leading-tight" data-testid="movie-title">
              {details.title}
            </h1>

            {#if details.stars?.length}
              <p class="text-xs sm:text-sm text-slate-400">
                <span class="text-slate-500">Starring</span> <span data-testid="movie-cast">{details.stars.join(', ')}</span>
              </p>
            {/if}

            {#if details.overview}
              <p class="text-sm text-slate-300 leading-relaxed max-w-3xl" data-testid="movie-synopsis">
                {details.overview}
              </p>
            {:else if details.degraded}
              <p class="text-xs text-amber-300/90 italic">
                Full IMDb metadata is currently unavailable, but you can still search indexers and download releases below.
              </p>
            {/if}

            <!-- Library Availability Banner -->
            <div class="flex flex-wrap items-center gap-3 pt-1" data-testid="movie-availability">
              {#if onDisk || badgeLabel}
                <span
                  class="inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-semibold {libraryBadgeTone(statusKey)}"
                  data-testid="availability-badge"
                  data-status={statusKey ?? 'available'}
                >
                  {badgeLabel ?? 'In Library'}
                </span>
              {:else}
                <span class="inline-flex items-center rounded-lg bg-onyx-raised/80 border border-onyx-border px-2.5 py-1 text-xs text-slate-400" data-testid="availability-none">
                  Not on disk
                </span>
              {/if}
              {#if onDisk}
                <span class="text-xs text-slate-500 font-mono truncate max-w-md" data-testid="library-path" title={onDisk.path}>
                  {onDisk.path}
                </span>
              {/if}
            </div>
          </div>

          <!-- Primary CTA row -->
          <div class="flex flex-wrap items-center gap-3 pt-2" data-testid="movie-actions">
            <button
              class="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-60 text-white text-sm font-semibold shadow-lg shadow-indigo-950/60 transition-colors cursor-pointer"
              type="button"
              disabled={page.downloadingBest}
              data-testid="download-best"
              onclick={() => void downloadBest()}
            >
              {#if page.downloadingBest}
                <span class="w-4 h-4 rounded-full border-2 border-white border-t-transparent animate-spin" aria-hidden="true"></span>
                <span>Finding Best…</span>
              {:else}
                <svg aria-hidden="true" class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v12m0 0l-4-4m4 4l4-4M4 19h16" />
                </svg>
                <span>Download Best</span>
              {/if}
            </button>

            <button
              class="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 bg-onyx-raised hover:bg-slate-700 border border-onyx-border text-slate-100 text-sm font-semibold transition-colors cursor-pointer"
              type="button"
              data-testid="choose-release"
              onclick={chooseRelease}
            >
              <span>Choose Release</span>
            </button>
          </div>
        </div>
      </div>
    </section>

    {#if details.similar?.length > 0}
      <MediaRail title={'More Like This'} items={details.similar} kind={'movie'} />
    {/if}
  {:else}
    <!-- Shimmer loading skeleton -->
    <div class="space-y-6" aria-busy="true" aria-label="Loading movie details">
      <div class="h-72 sm:h-80 rounded-2xl border border-onyx-border/60 skeleton-pulse"></div>
      <div class="h-5 w-36 rounded skeleton-pulse"></div>
      <div class="flex gap-4 overflow-hidden">
        {#each [0, 1, 2, 3, 4] as _}
          <div class="w-36 shrink-0 aspect-[2/3] rounded-xl skeleton-pulse"></div>
        {/each}
      </div>
    </div>
  {/if}

  {#if drawerItems !== null}
    <ReleaseDrawer items={drawerItems} scope={'movie'} title={page.details?.title ?? 'Releases'} />
  {/if}
</div>
