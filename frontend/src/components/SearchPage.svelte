<!-- /search?q= unified search view: queries Movies and TV Shows in parallel
     with grouped filter tabs, responsive poster grids, and per-source error
     resilience. -->
<script lang="ts">
  import PosterCard from './PosterCard.svelte';
  import { route } from '../lib/router.svelte';
  import { perform, errors, movies, retryMovies, retryTv, tv } from '../lib/stores/search.svelte';
  import { findMovie, findShow } from '../lib/stores/library.svelte';
  import type { MediaItem } from '../lib/api';

  const match = $derived(route());
  const query = $derived(match?.view === 'search' ? match.params.q ?? '' : '');

  let searching = $state(false);

  $effect(() => {
    if (query) {
      searching = true;
      void perform(query).finally(() => {
        searching = false;
      });
    } else {
      searching = false;
    }
  });

  const filter = $state({ tab: 'All' as 'All' | 'Movies' | 'TV Shows' });

  const results = $derived(errors());
  const movieRows = $derived(movies());
  const tvRows = $derived(tv());
  const showMovies = $derived(filter.tab === 'All' || filter.tab === 'Movies');
  const showTv = $derived(filter.tab === 'All' || filter.tab === 'TV Shows');
  const rowCount = $derived((showMovies ? movieRows.length : 0) + (showTv ? tvRows.length : 0));

  function moviePillId(row: MediaItem): string | null {
    const id = row.imdb_id ?? row.id;
    if (id === undefined || id === '') return null;
    return findMovie(String(id)) ? String(id) : null;
  }

  function showPillId(row: MediaItem): string | null {
    const id = row.tmdb_id ?? row.id;
    if (id === undefined || id === '') return null;
    const numeric = Number(id);
    if (Number.isNaN(numeric)) return null;
    return findShow(numeric) ? String(id) : null;
  }
</script>

<div class="flex flex-col gap-6" data-testid="search-page" data-query={query}>
  <!-- Header -->
  <div>
    <h1 class="text-2xl sm:text-3xl font-black text-white tracking-tight" data-testid="search-heading">
      {query ? `Search “${query}”` : 'Search'}
    </h1>
    <p class="mt-1 text-xs sm:text-sm text-slate-400">
      Searching IMDb movies and TVMaze series in parallel
    </p>
  </div>

  <!-- Segmented filter tabs -->
  <div class="inline-flex flex-wrap items-center gap-2 p-1 rounded-xl bg-onyx-surface border border-onyx-border w-fit" data-testid="search-tabs">
    <button
      class="rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-colors cursor-pointer {filter.tab === 'All'
        ? 'bg-indigo-600 text-white shadow-sm'
        : 'text-slate-400 hover:text-white'}"
      type="button"
      data-testid="tab-all"
      data-active={filter.tab === 'All'}
      onclick={() => (filter.tab = 'All')}
    >
      All <span class="ml-1 opacity-75 font-mono">({movieRows.length + tvRows.length})</span>
    </button>
    <button
      class="inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-colors cursor-pointer {filter.tab === 'Movies'
        ? 'bg-indigo-600 text-white shadow-sm'
        : 'text-slate-400 hover:text-white'}"
      type="button"
      data-testid="tab-movies"
      data-active={filter.tab === 'Movies'}
      onclick={() => (filter.tab = 'Movies')}
    >
      <span>Movies</span>
      <span
        class="rounded-full px-1.5 py-0.5 text-[10px] font-mono {filter.tab === 'Movies'
          ? 'bg-white/20 text-white'
          : 'bg-onyx-raised text-slate-300'}"
        data-testid="badge-movies"
        data-count={movieRows.length}
      >{String(movieRows.length)}</span>
    </button>
    <button
      class="inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-colors cursor-pointer {filter.tab === 'TV Shows'
        ? 'bg-indigo-600 text-white shadow-sm'
        : 'text-slate-400 hover:text-white'}"
      type="button"
      data-testid="tab-tv"
      data-active={filter.tab === 'TV Shows'}
      onclick={() => (filter.tab = 'TV Shows')}
    >
      <span>TV Shows</span>
      <span
        class="rounded-full px-1.5 py-0.5 text-[10px] font-mono {filter.tab === 'TV Shows'
          ? 'bg-white/20 text-white'
          : 'bg-onyx-raised text-slate-300'}"
        data-testid="badge-tv"
        data-count={tvRows.length}
      >{String(tvRows.length)}</span>
    </button>
  </div>

  <!-- Per-source partial error cards -->
  {#if showMovies && results.movies !== null}
    <div
      class="rounded-xl px-4 py-3 bg-amber-950/40 border border-amber-700/50 text-amber-200 text-xs sm:text-sm flex items-center justify-between gap-3"
      data-testid="error-movies"
      role="status"
      aria-live="polite"
    >
      <span data-testid="error-movies-message">{results.movies}</span>
      <button
        class="rounded-lg px-3 py-1.5 bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-100 text-xs font-semibold cursor-pointer shrink-0"
        type="button"
        data-testid="retry-movies"
        onclick={retryMovies}
      >
        Retry movies
      </button>
    </div>
  {/if}
  {#if showTv && results.tv !== null}
    <div
      class="rounded-xl px-4 py-3 bg-amber-950/40 border border-amber-700/50 text-amber-200 text-xs sm:text-sm flex items-center justify-between gap-3"
      data-testid="error-tv"
      role="status"
      aria-live="polite"
    >
      <span data-testid="error-tv-message">{results.tv}</span>
      <button
        class="rounded-lg px-3 py-1.5 bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-100 text-xs font-semibold cursor-pointer shrink-0"
        type="button"
        data-testid="retry-tv"
        onclick={retryTv}
      >
        Retry TV
      </button>
    </div>
  {/if}

  <!-- Loading skeletons -->
  {#if searching && rowCount === 0}
    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4 sm:gap-5" aria-busy="true">
      {#each [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] as _}
        <div class="space-y-2">
          <div class="aspect-[2/3] rounded-xl skeleton-pulse"></div>
          <div class="h-3.5 w-4/5 rounded skeleton-pulse"></div>
        </div>
      {/each}
    </div>
  {/if}

  <!-- Movies section -->
  {#if showMovies && movieRows.length > 0}
    <section class="flex flex-col gap-3.5" data-testid="rows-movies" aria-label="Movie results">
      <h2 class="text-base sm:text-lg font-bold text-white">Movies</h2>
      <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4 sm:gap-5">
        {#each movieRows as row (String(row.imdb_id ?? row.id ?? row.title ?? ''))}
          <div class="relative flex flex-col gap-1.5" data-testid="search-row" data-kind="movie">
            <PosterCard item={row} kind={'movie'} fluid={true} />
            {#if moviePillId(row) !== null}
              <span
                class="w-fit inline-flex items-center gap-1 rounded-md bg-emerald-500/15 border border-emerald-500/35 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-300"
                data-testid="availability-pill"
                data-id={moviePillId(row) ?? ''}
              >
                In Library
              </span>
            {/if}
          </div>
        {/each}
      </div>
    </section>
  {/if}

  <!-- TV Shows section -->
  {#if showTv && tvRows.length > 0}
    <section class="flex flex-col gap-3.5" data-testid="rows-tv" aria-label="TV show results">
      <h2 class="text-base sm:text-lg font-bold text-white">TV Shows</h2>
      <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4 sm:gap-5">
        {#each tvRows as row (String(row.tmdb_id ?? row.id ?? row.title ?? ''))}
          <div class="relative flex flex-col gap-1.5" data-testid="search-row" data-kind="tv">
            <PosterCard item={row} kind={'tv'} fluid={true} />
            {#if showPillId(row) !== null}
              <span
                class="w-fit inline-flex items-center gap-1 rounded-md bg-emerald-500/15 border border-emerald-500/35 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-300"
                data-testid="availability-pill"
                data-id={showPillId(row) ?? ''}
              >
                In Library
              </span>
            {/if}
          </div>
        {/each}
      </div>
    </section>
  {/if}

  {#if !searching && rowCount === 0}
    <div
      class="rounded-2xl py-16 px-6 bg-onyx-surface/70 border border-onyx-border text-center text-sm text-slate-400"
      data-testid="search-empty"
      role="status"
      aria-live="polite"
    >
      <span data-testid="search-empty-message">
        {query ? `No results for “${query}”. Check the spelling or try a different title.` : 'Use the search bar at the top of the screen or press Ctrl+K to search.'}
      </span>
    </div>
  {/if}
</div>
