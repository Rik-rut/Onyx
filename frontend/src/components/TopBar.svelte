<!-- Persistent top header: active view breadcrumb, prominent global Ctrl+K
     search bar trigger, and live backend connection pill. -->
<script lang="ts">
  import { navigate, route } from '../lib/router.svelte';
  import { wsConnected } from '../lib/stores/queue.svelte';
  import { setPalette } from '../lib/stores/ui.svelte';

  const labels: Record<string, string> = {
    discover: 'Discover',
    movies: 'Movies',
    tv: 'TV Shows',
    search: 'Search',
    movie: 'Movie details',
    tvshow: 'TV details',
    library: 'Library',
    monitored: 'Monitored',
    queue: 'Queue',
    settings: 'Settings',
  };

  const viewLabel = $derived(route() ? labels[route()?.view ?? 'discover'] : 'Not Found');
  const live = $derived(wsConnected());
</script>

<header
  class="sticky top-0 z-30 h-16 px-4 sm:px-6 lg:px-8 flex items-center justify-between gap-4 bg-onyx-obsidian/85 backdrop-blur-md border-b border-onyx-border/80"
  data-testid="top-bar"
>
  <!-- Left: Mobile Onyx logo + current route label -->
  <div class="flex items-center gap-3 min-w-0">
    <a
      href="/"
      class="lg:hidden font-black text-lg tracking-[0.26em] bg-gradient-to-r from-white via-slate-200 to-indigo-400 bg-clip-text text-transparent select-none"
      data-testid="brand"
      onclick={(event) => {
        event.preventDefault();
        navigate('/');
      }}
    >
      ONYX
    </a>
    <span class="lg:hidden h-4 w-px bg-onyx-border" aria-hidden="true"></span>
    <span class="text-sm sm:text-base font-semibold text-white truncate" data-testid="view-label">{viewLabel}</span>
  </div>

  <!-- Right: Global search trigger + status dot -->
  <div class="flex items-center gap-3">
    <button
      class="group flex items-center justify-between gap-3 w-44 sm:w-72 md:w-80 rounded-xl px-3.5 py-2 bg-onyx-surface/90 hover:bg-onyx-raised border border-onyx-border hover:border-slate-600 text-xs sm:text-sm text-onyx-muted hover:text-slate-200 transition-colors cursor-pointer"
      type="button"
      data-testid="palette-trigger"
      title="Search movies, TV shows, or your local library (Ctrl+K)"
      onclick={() => setPalette(true, '')}
    >
      <span class="flex items-center gap-2.5 min-w-0">
        <svg aria-hidden="true" class="w-4 h-4 shrink-0 text-slate-400 group-hover:text-indigo-400 transition-colors" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-4.35-4.35M17 11a6 6 0 11-12 0 6 6 0 0112 0z" />
        </svg>
        <span class="truncate">Search movies, TV, library…</span>
      </span>
      <span
        class="hidden sm:inline-flex items-center gap-1 text-[10px] font-mono text-slate-400 shrink-0"
        data-testid="palette-hint"
      >
        <kbd class="rounded-md bg-onyx-obsidian border border-onyx-border px-1.5 py-0.5">Ctrl</kbd>
        <kbd class="rounded-md bg-onyx-obsidian border border-onyx-border px-1.5 py-0.5">K</kbd>
      </span>
    </button>

    <div
      class="hidden sm:inline-flex items-center gap-2 rounded-full px-2.5 py-1 bg-onyx-surface border border-onyx-border/80 text-[11px] font-medium {live ? 'text-emerald-300' : 'text-amber-300'}"
      role="status"
      aria-label={live ? 'Live backend connection' : 'Reconnecting to backend'}
    >
      <span
        class="w-2 h-2 rounded-full {live ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.65)]' : 'bg-amber-400'}"
        data-testid="topbar-connection-dot"
        aria-hidden="true"
      ></span>
      <span>{live ? 'Live' : 'Offline'}</span>
    </div>
  </div>
</header>
