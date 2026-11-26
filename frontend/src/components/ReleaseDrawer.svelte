<!-- Right-side slide-over Release Drawer: resolution chips, sort controls,
     scored release cards, per-row Download with HTTP 409 duplicate confirmation,
     Escape & backdrop dismiss, and contained scroll. -->
<script lang="ts">
  import { api, ApiError, filterReleases, formatBytes, isDuplicateDownload, sortReleases } from '../lib/api';
  import type { ReleaseItem } from '../lib/api';
  import { askConfirmation, closeDrawer, drawer, pushToast } from '../lib/stores/ui.svelte';

  const drawerProps = $props();
  const items = $derived((drawerProps.items as ReleaseItem[]) ?? []);
  const scope = $derived((drawerProps.scope as 'movie' | 'tv') ?? 'movie');
  const title = $derived((drawerProps.title as string) ?? 'Releases');

  // Scope-aware drawer title: for TV, the drawer target carries the requested
  // season/episode, so "Wayward Pines" reads "Wayward Pines S02E05".
  const drawerTarget = $derived((drawer()?.target ?? {}) as Record<string, unknown>);
  const scopeSuffix = $derived(
    scope === 'tv'
      ? [
          typeof drawerTarget.season === 'number'
            ? `S${String(drawerTarget.season).padStart(2, '0')}`
            : '',
          typeof drawerTarget.episode === 'number'
            ? `E${String(drawerTarget.episode).padStart(2, '0')}`
            : '',
        ].filter(Boolean).join('')
      : '',
  );
  const displayTitle = $derived(scopeSuffix ? `${title} ${scopeSuffix}` : title);

  const CHIPS: Array<{ label: string; value: string }> = [
    { label: 'All', value: 'All' },
    { label: '4K / 2160p', value: '4K / 2160p' },
    { label: '1080p', value: '1080p' },
    { label: '720p', value: '720p' },
  ];
  const SORTS: Array<{ label: string; value: 'score' | 'seeds' | 'size' }> = [
    { label: 'Best Score', value: 'score' },
    { label: 'Most Seeders', value: 'seeds' },
    { label: 'Smallest Size', value: 'size' },
  ];

  let chip = $state('All');
  let sortMode = $state<'score' | 'seeds' | 'size'>('score');
  let busyHash = $state<string | null>(null);

  const shown = $derived(sortReleases(filterReleases(items, chip), sortMode));

  $effect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') closeDrawer();
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  });

  function detailText(failure: unknown): string {
    if (failure instanceof ApiError) return failure.detail;
    return String(failure);
  }

  function scoreTone(score: number): string {
    if (score >= 700) return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/35';
    if (score >= 400) return 'bg-indigo-500/15 text-indigo-300 border-indigo-500/35';
    return 'bg-amber-500/15 text-amber-300 border-amber-500/35';
  }

  async function queueRow(row: ReleaseItem): Promise<void> {
    const target = drawer()?.target ?? {};
    busyHash = row.infohash || row.title;
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
        id: `drawer-${row.infohash}`,
        title: 'Already in library',
        message: `"${row.title}" is already in the library. Download it again?`,
        kind: 'duplicate',
        confirmLabel: 'Download again',
      });
      if (!approved) return;
      try {
        await api.downloadRelease(row, target, true);
        pushToast({
          message: `Queued ${row.title} again`,
          kind: 'success',
          actionLabel: 'Open queue',
          actionPath: '/queue',
        });
      } catch (retryFailure) {
        pushToast({ message: `Could not queue ${row.title}: ${detailText(retryFailure)}`, kind: 'error' });
      }
    } finally {
      busyHash = null;
    }
  }
</script>

<!-- Frosted backdrop -->
<div
  class="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm contain-scroll"
  data-testid="drawer-backdrop"
  aria-hidden="true"
  onclick={closeDrawer}
></div>

<!-- Right-side slide-over panel -->
<div
  class="drawer-slide-in fixed inset-y-0 right-0 z-50 w-full max-w-xl bg-onyx-surface border-l border-onyx-border shadow-2xl shadow-black/80 flex flex-col contain-scroll"
  data-testid="release-drawer"
  role="dialog"
  aria-modal="true"
  aria-label={displayTitle}
>
  <!-- Drawer header -->
  <div class="px-5 py-4 border-b border-onyx-border/80 flex items-start justify-between gap-4 bg-onyx-obsidian/50">
    <div class="min-w-0">
      <p class="text-[10px] font-bold uppercase tracking-[0.16em] text-indigo-400" data-testid="drawer-scope">
        {scope === 'movie' ? 'Movie releases' : 'TV releases'}
      </p>
      <h2 class="mt-0.5 text-base sm:text-lg font-bold text-white truncate" data-testid="drawer-title" data-scope={scope}>
        {displayTitle}
      </h2>
    </div>
    <button
      class="w-8 h-8 rounded-lg bg-onyx-raised hover:bg-slate-700 border border-onyx-border text-slate-300 hover:text-white flex items-center justify-center transition-colors shrink-0 cursor-pointer"
      type="button"
      data-testid="drawer-close"
      aria-label="Close release drawer"
      onclick={closeDrawer}
    >
      <span aria-hidden="true" class="text-lg leading-none">&times;</span>
    </button>
  </div>

  <!-- Filter chips + sort controls -->
  <div class="px-5 py-3 border-b border-onyx-border/80 bg-onyx-obsidian/30 space-y-2.5">
    <div class="flex flex-wrap items-center gap-1.5" data-testid="drawer-chips" role="group" aria-label="Resolution filter">
      <span class="text-[11px] font-medium text-slate-400 mr-1">Quality:</span>
      {#each CHIPS as option}
        {@const active = option.value === chip}
        <button
          class="rounded-full px-3 py-1 text-xs font-semibold border transition-colors cursor-pointer {active
            ? 'bg-indigo-600 text-white border-indigo-500'
            : 'bg-onyx-surface text-slate-300 border-onyx-border hover:border-slate-500 hover:text-white'}"
          type="button"
          data-testid="drawer-chip"
          data-chip={option.value}
          aria-pressed={active}
          onclick={() => (chip = option.value)}
        >
          {option.label}
        </button>
      {/each}
    </div>

    <div class="flex flex-wrap items-center gap-1.5" data-testid="drawer-sorts" role="group" aria-label="Sort order">
      <span class="text-[11px] font-medium text-slate-400 mr-1">Sort:</span>
      {#each SORTS as option}
        {@const active = option.value === sortMode}
        <button
          class="rounded-lg px-2.5 py-1 text-xs font-medium border transition-colors cursor-pointer {active
            ? 'bg-onyx-raised text-indigo-300 border-indigo-500/50'
            : 'bg-transparent text-slate-400 border-onyx-border/70 hover:text-white hover:border-slate-500'}"
          type="button"
          data-testid="drawer-sort"
          data-sort={option.value}
          aria-pressed={active}
          onclick={() => (sortMode = option.value)}
        >
          {option.label}
        </button>
      {/each}
    </div>
  </div>

  <!-- Scrollable release cards -->
  <div class="flex-1 overflow-y-auto p-4 sm:p-5 space-y-3 contain-scroll" data-testid="drawer-rows">
    {#if drawer()?.loading}
      <div class="py-16 flex flex-col items-center justify-center gap-3 text-slate-400" data-testid="drawer-loading" role="status">
        <span class="w-7 h-7 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin" aria-hidden="true"></span>
        <span class="text-xs sm:text-sm">Searching indexers and scoring releases…</span>
      </div>
    {:else if shown.length === 0}
      <div class="py-16 text-center space-y-2" data-testid="drawer-empty">
        <p class="text-sm font-medium text-slate-300">No releases match this filter.</p>
        {#if chip !== 'All' && items.length > 0}
          <button
            type="button"
            class="text-xs font-semibold text-indigo-400 hover:text-indigo-300 underline underline-offset-2 cursor-pointer"
            onclick={() => (chip = 'All')}
          >
            Show all {items.length} releases
          </button>
        {/if}
      </div>
    {:else}
      {#each shown as row, i ((row.infohash || row.title) + ':' + i)}
        {@const isBusy = busyHash === (row.infohash || row.title)}
        <article
          class="rounded-xl p-4 bg-onyx-obsidian/70 hover:bg-onyx-raised/60 border border-onyx-border/80 hover:border-slate-600 transition-colors flex flex-col gap-3"
          data-testid="release-row"
          data-title={row.title}
          data-indexer={row.indexer}
          data-score={row.score}
          data-seeds={row.seeds}
          data-peers={row.peers}
          data-size={formatBytes(row.size_bytes)}
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1 space-y-1.5">
              <div class="flex flex-wrap items-center gap-1.5">
                <span class="rounded-md border px-2 py-0.5 text-[11px] font-bold tabular-nums {scoreTone(row.score)}">
                  Score {row.score}
                </span>
                <span class="rounded-md bg-onyx-raised border border-onyx-border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-slate-300">
                  {row.indexer}
                </span>
                {#if row.resolution}
                  <span class="rounded-md bg-sky-500/15 border border-sky-500/30 px-2 py-0.5 text-[10px] font-bold text-sky-300">
                    {row.resolution}
                  </span>
                {/if}
                {#if row.codec}
                  <span class="text-[11px] text-slate-400 font-mono">{row.codec}</span>
                {/if}
                {#if row.is_pack}
                  <span class="rounded-md bg-indigo-500/20 border border-indigo-400/35 px-2 py-0.5 text-[10px] font-bold uppercase text-indigo-200">
                    Season Pack
                  </span>
                {/if}
                {#if row.season_label}
                  <span
                    class="rounded-md bg-emerald-500/15 border border-emerald-400/30 px-2 py-0.5 text-[10px] font-bold font-mono text-emerald-300"
                    data-testid="release-coverage"
                    data-season-label={row.season_label}
                  >
                    {row.season_label}
                  </span>
                {/if}
              </div>

              <h3 class="text-xs sm:text-sm font-medium text-slate-100 break-words leading-snug" title={row.title}>
                {row.title}
              </h3>

              {#if row.raw_title && row.raw_title !== row.title}
                <p
                  class="font-mono text-[10px] sm:text-[11px] leading-snug break-all text-slate-500"
                  data-testid="release-raw-title"
                  title={row.raw_title}
                >
                  {row.raw_title}
                </p>
              {/if}
              <div class="flex flex-wrap items-center gap-3 text-xs font-mono text-slate-400">
                <span>{formatBytes(row.size_bytes)}</span>
                <span class="text-emerald-400 font-semibold">↓ {row.seeds} seeds</span>
                <span class="text-slate-500">↑ {row.peers} peers</span>
              </div>

              {#if row.reasons?.length}
                <p class="text-[11px] text-slate-500 italic line-clamp-2">{row.reasons[0]}</p>
              {/if}
            </div>

            <button
              class="shrink-0 rounded-xl px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-60 text-white text-xs font-semibold shadow-sm transition-colors cursor-pointer"
              type="button"
              disabled={isBusy}
              data-testid="release-download"
              data-row={row.title}
              onclick={() => void queueRow(row)}
            >
              {isBusy ? 'Queuing…' : 'Download'}
            </button>
          </div>
        </article>
      {/each}
    {/if}
  </div>
</div>
