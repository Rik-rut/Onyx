<!-- Horizontal scrollable rail of portrait poster cards with desktop scroll
     arrows and edge scrollability fade hints. -->
<script lang="ts">
  import PosterCard from './PosterCard.svelte';
  import type { MediaItem } from '../lib/api';

  let {
    title,
    items,
    kind,
  }: {
    title: string;
    items: MediaItem[];
    kind: 'movie' | 'tv';
  } = $props();

  let scroller = $state<HTMLDivElement | null>(null);

  function nudge(direction: -1 | 1): void {
    if (!scroller) return;
    const distance = Math.max(320, Math.round(scroller.clientWidth * 0.75));
    scroller.scrollBy?.({ left: direction * distance, behavior: 'smooth' });
  }
</script>

<section
  class="flex flex-col gap-3"
  data-testid="media-rail"
  data-rail={title}
  aria-label={title}
>
  <div class="flex items-center justify-between gap-3">
    <h2 class="text-base sm:text-lg font-bold text-white tracking-tight">{title}</h2>
    <div class="hidden sm:flex items-center gap-1.5">
      <button
        type="button"
        aria-label={`Scroll ${title} left`}
        class="w-7 h-7 rounded-lg bg-onyx-surface hover:bg-onyx-raised border border-onyx-border text-slate-400 hover:text-white flex items-center justify-center transition-colors cursor-pointer"
        onclick={() => nudge(-1)}
      >
        <svg aria-hidden="true" class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
      </button>
      <button
        type="button"
        aria-label={`Scroll ${title} right`}
        class="w-7 h-7 rounded-lg bg-onyx-surface hover:bg-onyx-raised border border-onyx-border text-slate-400 hover:text-white flex items-center justify-center transition-colors cursor-pointer"
        onclick={() => nudge(1)}
      >
        <svg aria-hidden="true" class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </button>
    </div>
  </div>

  <div
    bind:this={scroller}
    class="rail-fade no-scrollbar flex items-start gap-3.5 sm:gap-4 overflow-x-auto pb-2"
  >
    {#each items as row (String(row.imdb_id ?? row.tmdb_id ?? row.id ?? row.title ?? ''))}
      <PosterCard item={row} {kind} />
    {/each}
  </div>
</section>
