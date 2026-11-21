<!-- Dedicated /movies and /tv genre-filtered endless browse pages. -->
<script lang="ts">
  import { MOVIE_GENRES, TV_GENRES } from '../lib/api';
  import { currentPath, navigate, route, setLocation } from '../lib/router.svelte';
  import PosterCard from './PosterCard.svelte';
  import {
    ensureVisible,
    errorMessage,
    feedGenres,
    gridHost,
    gridRows,
    isLoading,
    loadMore,
    noResults,
    refresh,
    sentinelHost,
    visible,
  } from '../lib/stores/browse.svelte';

  const match = $derived(route());
  const view = $derived(match?.view === 'tv' ? 'tv' : 'movies');
  const kind = $derived(view === 'tv' ? 'tv' : 'movie');
  const genre = $derived(match?.params?.genre ?? '');
  const heading = $derived(view === 'tv' ? 'TV Shows' : 'Movies');

  // Show curated genre chips for the active media type, plus any additional
  // genres observed in loaded items (keeping the chip list stable when filtering).
  const chips = $derived.by(() => {
    const base = kind === 'tv' ? TV_GENRES : MOVIE_GENRES;
    const dynamic = feedGenres();
    const merged = new Set<string>([...dynamic, ...base]);
    if (genre) merged.add(genre);
    return [...merged];
  });

  const items = $derived(visible());
  const loading = $derived(isLoading());
  const err = $derived(errorMessage());

  $effect(() => {
    void refresh(kind, genre);
  });

  $effect(() => {
    void items.length;
    ensureVisible(gridHost(), gridRows(), () => loadMore(kind, genre), sentinelHost());
  });

  function selectGenre(nextGenre: string): void {
    const target = nextGenre === genre ? '' : nextGenre;
    const search = target ? `?genre=${encodeURIComponent(target)}` : '';
    setLocation(currentPath(), search);
    try {
      window.history.pushState({}, '', `${currentPath()}${search}`);
    } catch {
      // jsdom / test fallback
    }
  }

  function clearFilter(): void {
    setLocation(currentPath(), '');
    try {
      window.history.pushState({}, '', currentPath());
    } catch {
      // jsdom / test fallback
    }
  }
</script>

<div class="flex flex-col gap-6" data-testid="browse-page" data-view={view}>
  <!-- Header + active filter indicator -->
  <div class="flex flex-wrap items-end justify-between gap-3">
    <div>
      <h1 class="text-2xl sm:text-3xl font-black text-white tracking-tight">
        {heading}{#if genre}<span class="text-indigo-400"> · {genre}</span>{/if}
      </h1>
      <p class="mt-1 text-xs sm:text-sm text-slate-400" data-testid="browse-filter" data-genre={genre}>
        {genre ? `Showing ${heading.toLowerCase()} in ${genre}` : `Explore all ${heading.toLowerCase()} or filter by genre`}
      </p>
    </div>

    {#if genre}
      <button
        class="inline-flex items-center gap-1.5 rounded-xl px-3.5 py-2 bg-onyx-surface hover:bg-onyx-raised border border-onyx-border text-xs font-semibold text-slate-300 hover:text-white transition-colors cursor-pointer"
        type="button"
        data-testid="browse-clear-filter"
        onclick={clearFilter}
      >
        <span>Clear filter</span>
        <span aria-hidden="true">&times;</span>
      </button>
    {:else}
      <button
        class="sr-only"
        type="button"
        data-testid="browse-clear-filter"
        onclick={clearFilter}
      >
        Clear filter
      </button>
    {/if}
  </div>

  <!-- Genre chips -->
  <div class="flex flex-wrap items-center gap-2" role="group" aria-label="Filter by genre">
    {#each chips as chip (chip)}
      {@const active = genre === chip}
      <button
        class="rounded-full px-3.5 py-1.5 text-xs font-semibold border transition-colors cursor-pointer {active
          ? 'bg-indigo-600 text-white border-indigo-500 shadow-sm shadow-indigo-950/60'
          : 'bg-onyx-surface/80 text-slate-300 border-onyx-border hover:border-slate-500 hover:text-white'}"
        type="button"
        data-testid="browse-genre-chip"
        data-genre={chip}
        aria-pressed={active}
        onclick={() => selectGenre(chip)}
      >
        {chip}
      </button>
    {/each}
  </div>

  <!-- Responsive multi-column poster grid -->
  {#if items.length > 0}
    <div
      class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4 sm:gap-5"
      data-testid="browse-grid"
    >
      {#each items as item (String(item.imdb_id ?? item.tmdb_id ?? item.id ?? item.title ?? ''))}
        <PosterCard {item} {kind} fluid={true} />
      {/each}
    </div>
  {:else if !noResults() && !err}
    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4 sm:gap-5" aria-busy="true">
      {#each [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] as _}
        <div class="space-y-2">
          <div class="aspect-[2/3] rounded-xl skeleton-pulse"></div>
          <div class="h-3.5 w-3/4 rounded skeleton-pulse"></div>
        </div>
      {/each}
    </div>
  {:else}
    <div class="hidden" data-testid="browse-grid"></div>
  {/if}

  {#if loading && items.length > 0}
    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4 sm:gap-5" aria-hidden="true">
      {#each [0, 1, 2, 3, 4, 5] as _}
        <div class="aspect-[2/3] rounded-xl skeleton-pulse"></div>
      {/each}
    </div>
  {/if}

  {#if err}
    <div class="rounded-2xl p-5 bg-onyx-surface border border-rose-800/50 flex items-center justify-between gap-4" role="alert">
      <p class="text-xs sm:text-sm text-rose-300">{err}</p>
      <button
        type="button"
        class="rounded-xl px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold cursor-pointer"
        onclick={() => void refresh(kind, genre)}
      >
        Try again
      </button>
    </div>
  {/if}

  {#if noResults()}
    <div
      class="rounded-2xl py-14 px-6 bg-onyx-surface/70 border border-onyx-border text-center space-y-3"
      data-testid="browse-no-results"
      role="status"
      aria-live="polite"
    >
      <p class="text-sm font-medium text-slate-300" data-testid="browse-no-results-text">
        No results{genre ? ` in ${genre}` : ''} — try another genre.
      </p>
      {#if genre}
        <button
          type="button"
          class="rounded-xl px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold cursor-pointer"
          onclick={clearFilter}
        >
          Show all {heading.toLowerCase()}
        </button>
      {/if}
    </div>
  {/if}

  <!-- Bottom infinite scroll sentinel -->
  <div class="h-8 w-full" data-testid="browse-sentinel" aria-hidden="true"></div>
</div>
