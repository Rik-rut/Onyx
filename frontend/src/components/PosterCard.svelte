<!-- Portrait 2:3 media poster card with hover zoom, rating & library overlay
     pills, image-error fallback, and SPA pushState navigation. -->
<script lang="ts">
  import { navigate, pathFor } from '../lib/router.svelte';
  import { libraryBadgeLabel, libraryBadgeTone } from '../lib/api';
  import type { MediaItem } from '../lib/api';

  let {
    item,
    kind,
    fluid = false,
  }: {
    item: MediaItem;
    kind: 'movie' | 'tv';
    fluid?: boolean;
  } = $props();

  let imageBroken = $state(false);

  const id = $derived(kind === 'movie' ? item.imdb_id ?? item.id : item.tmdb_id ?? item.id);
  const clickable = $derived(id !== undefined && id !== '');
  const href = $derived(
    clickable
      ? pathFor(
          kind === 'movie' ? 'movie' : 'tvshow',
          kind === 'movie' ? { imdbId: String(id) } : { showId: String(id) },
        )
      : undefined,
  );
  const display = $derived(item.title ?? item.name ?? 'Untitled');
  const initials = $derived(
    display
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0]?.toUpperCase() ?? '')
      .join(''),
  );
  const statusLabel = $derived(libraryBadgeLabel(item.library_status));
  const showPoster = $derived(Boolean(item.poster) && !imageBroken);

  // Reset error flag if a recycled card receives a different poster URL.
  $effect(() => {
    void item.poster;
    imageBroken = false;
  });
</script>

<a
  class="{fluid ? 'w-full' : 'w-36 sm:w-40 shrink-0'} group flex flex-col text-left focus:outline-none {clickable
    ? 'cursor-pointer'
    : 'cursor-default'}"
  {href}
  data-testid="poster-card"
  data-kind={kind}
  data-clickable={clickable}
  data-id={String(id ?? '')}
  onclick={(event) => {
    if (!href) return;
    event.preventDefault();
    navigate(href);
  }}
>
  <div
    class="relative w-full aspect-[2/3] rounded-xl overflow-hidden bg-onyx-surface border border-onyx-border/80 group-hover:border-indigo-500/80 shadow-md shadow-black/40 transition-colors"
  >
    {#if showPoster}
      <img
        class="w-full h-full object-cover poster-zoom"
        src={item.poster}
        alt={`Poster for ${display}`}
        loading="lazy"
        data-testid="poster-image"
        onerror={() => (imageBroken = true)}
      />
    {:else}
      <div class="w-full h-full bg-gradient-to-br from-slate-800 via-onyx-surface to-indigo-950/60 flex flex-col items-center justify-center p-3 text-center gap-1.5">
        <span class="text-xl font-black tracking-wider text-slate-500/80">{initials || '?'}</span>
        <span class="text-[11px] font-medium text-slate-400 line-clamp-3">{display}</span>
      </div>
    {/if}

    <!-- Subtle bottom vignette for overlay readability -->
    <div class="pointer-events-none absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-black/75 via-black/25 to-transparent" aria-hidden="true"></div>

    {#if item.rating !== undefined && item.rating !== null && item.rating !== ''}
      <span
        class="absolute top-2 right-2 inline-flex items-center gap-0.5 rounded-md bg-black/75 backdrop-blur-sm border border-white/10 px-1.5 py-0.5 text-[11px] font-bold text-amber-300 tabular-nums"
        data-testid="rating-badge"
      >
        ★ {item.rating}
      </span>
    {/if}

    {#if statusLabel}
      <span
        class="absolute bottom-2 left-2 right-2 w-fit max-w-[calc(100%-1rem)] truncate inline-flex items-center rounded-md border backdrop-blur-sm px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide {libraryBadgeTone(item.library_status)}"
        data-testid="availability-badge"
        data-status={item.library_status}
      >
        {statusLabel}
      </span>
    {/if}
  </div>

  <div class="mt-2 px-0.5 space-y-0.5">
    <h3 class="text-xs sm:text-[13px] font-semibold text-slate-100 group-hover:text-indigo-300 transition-colors truncate">
      {display}
    </h3>
    {#if item.year}
      <p class="text-[11px] text-slate-500 font-mono">{item.year}</p>
    {/if}
  </div>
</a>
