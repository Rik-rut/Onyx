<!-- Discover home (/): cinematic mixed Hero Spotlight + Trending Movies,
     Trending TV Shows, and Top Rated Movies rails simultaneously. -->
<script lang="ts">
  import MediaRail from './MediaRail.svelte';
  import PosterCard from './PosterCard.svelte';
  import { libraryBadgeLabel, libraryBadgeTone } from '../lib/api';
  import { navigate, pathFor } from '../lib/router.svelte';
  import { ensureLoaded, errorText, failures, isLoading, payload, retryNow } from '../lib/stores/discover.svelte';

  $effect(() => ensureLoaded());

  const feed = $derived(payload());
  const spotlight = $derived(feed?.spotlight ?? null);
  const heroKind = $derived<'movie' | 'tv'>(spotlight?.tmdb_id !== undefined ? 'tv' : 'movie');
  const heroTitle = $derived(spotlight?.title ?? spotlight?.name ?? 'Featured');
  const heroStatus = $derived(libraryBadgeLabel(spotlight?.library_status));
  const loading = $derived(isLoading());
  const failCount = $derived(failures());

  function openSpotlight(): void {
    if (!spotlight) return;
    navigate(
      pathFor(
        heroKind === 'tv' ? 'tvshow' : 'movie',
        heroKind === 'tv'
          ? { showId: String(spotlight.tmdb_id ?? spotlight.id) }
          : { imdbId: String(spotlight.imdb_id ?? spotlight.id) },
      ),
    );
  }
</script>

<div class="flex flex-col gap-8" data-testid="discover-page">
  {#if feed}
    {#if spotlight}
      <section
        class="relative overflow-hidden rounded-2xl border border-onyx-border/80 bg-onyx-surface shadow-xl shadow-black/40"
        data-testid="hero-spotlight"
        aria-label="Featured spotlight"
      >
        {#if spotlight.poster}
          <img
            src={spotlight.poster}
            alt=""
            aria-hidden="true"
            class="absolute inset-0 w-full h-full object-cover opacity-25 blur-xl scale-110 pointer-events-none"
          />
        {/if}
        <div
          class="absolute inset-0 bg-gradient-to-r from-onyx-obsidian via-onyx-obsidian/90 to-onyx-obsidian/45 pointer-events-none"
          aria-hidden="true"
        ></div>

        <div class="relative p-5 sm:p-8 flex flex-col sm:flex-row items-start sm:items-center gap-6">
          <div class="shrink-0">
            <PosterCard item={spotlight} kind={heroKind} />
          </div>

          <div class="flex-1 min-w-0 space-y-3">
            <div class="flex flex-wrap items-center gap-2">
              <span class="px-2.5 py-0.5 rounded-md bg-indigo-600 text-white text-[10px] font-bold uppercase tracking-[0.18em]">
                Featured {heroKind === 'tv' ? 'Series' : 'Movie'}
              </span>
              {#if spotlight.rating}
                <span class="px-2 py-0.5 rounded-md bg-amber-500/15 border border-amber-500/30 text-amber-300 text-xs font-semibold">
                  ★ {spotlight.rating}
                </span>
              {/if}
              {#if spotlight.year}
                <span class="text-xs font-mono text-slate-300">{spotlight.year}</span>
              {/if}
              {#if spotlight.genres?.length}
                <span class="text-xs text-slate-400">{spotlight.genres.slice(0, 3).join(' • ')}</span>
              {/if}
              {#if heroStatus}
                <span class="px-2 py-0.5 rounded-md border text-[10px] font-bold uppercase tracking-wide {libraryBadgeTone(spotlight.library_status)}">
                  {heroStatus}
                </span>
              {/if}
            </div>

            <h1 class="text-2xl sm:text-3xl lg:text-4xl font-black text-white tracking-tight leading-tight">
              {heroTitle}
            </h1>

            {#if spotlight.overview}
              <p class="text-xs sm:text-sm text-slate-300 max-w-2xl leading-relaxed line-clamp-3">
                {spotlight.overview}
              </p>
            {:else}
              <p class="text-xs sm:text-sm text-slate-400 italic">
                Trending right now — explore releases, quality scores, and related titles.
              </p>
            {/if}

            <div class="pt-2 flex flex-wrap items-center gap-3">
              <button
                class="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold shadow-lg shadow-indigo-950/60 transition-colors cursor-pointer"
                type="button"
                data-testid="hero-cta"
                onclick={openSpotlight}
              >
                <span>View &amp; Download</span>
                <svg aria-hidden="true" class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
                </svg>
              </button>
              <button
                type="button"
                class="rounded-xl px-4 py-2.5 bg-white/[0.06] hover:bg-white/[0.12] border border-white/10 text-slate-200 text-sm font-medium transition-colors cursor-pointer"
                onclick={() => navigate(heroKind === 'tv' ? '/tv' : '/movies')}
              >
                Browse all {heroKind === 'tv' ? 'TV shows' : 'movies'}
              </button>
            </div>
          </div>
        </div>
      </section>
    {/if}

    {#if feed.trending_movies?.length}
      <MediaRail title="Trending Movies" items={feed.trending_movies} kind={'movie'} />
    {/if}
    {#if feed.trending_tv?.length}
      <MediaRail title="Trending TV Shows" items={feed.trending_tv} kind={'tv'} />
    {/if}
    {#if feed.top_rated_movies?.length}
      <MediaRail title="Top Rated Movies" items={feed.top_rated_movies} kind={'movie'} />
    {/if}
  {:else if failCount > 0}
    <div
      class="rounded-2xl p-6 bg-onyx-surface border border-amber-700/40 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4"
      data-testid="discover-error"
      role="status"
      aria-live="polite"
    >
      <div class="space-y-1">
        <p class="text-sm font-semibold text-amber-300">Unable to reach Discover feed</p>
        <p class="text-xs text-slate-400" data-testid="discover-error-message">{errorText()}</p>
      </div>
      <button
        class="rounded-xl px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold transition-colors cursor-pointer"
        type="button"
        data-testid="discover-retry"
        onclick={retryNow}
      >
        Retry now
      </button>
    </div>
  {:else}
    <!-- Shimmer loading skeleton -->
    <div class="space-y-8" aria-busy="true" aria-label="Loading Discover feed" data-testid="discover-loading">
      <div class="h-64 sm:h-72 rounded-2xl border border-onyx-border/60 skeleton-pulse"></div>
      {#each [0, 1] as _}
        <div class="space-y-3">
          <div class="h-5 w-40 rounded-md skeleton-pulse"></div>
          <div class="flex gap-4 overflow-hidden">
            {#each [0, 1, 2, 3, 4, 5] as __}
              <div class="w-36 sm:w-40 shrink-0 space-y-2">
                <div class="aspect-[2/3] rounded-xl skeleton-pulse"></div>
                <div class="h-3.5 w-3/4 rounded skeleton-pulse"></div>
              </div>
            {/each}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
