<!-- Transfer queue view (/queue): live header summary, magnet ingestion +
     manual import controls, status filter pills (All / Active / Seeding / Paused),
     real progress bars, priority/pause/resume controls, and confirmed delete. -->
<script lang="ts">
  import { api, ApiError, formatBytes, formatEta, formatSpeed } from '../lib/api';
  import { navigate, pathFor } from '../lib/router.svelte';
  import {
    backendDown,
    openSocket,
    refreshFromRest,
    retryDelayMs,
    retryNow,
    statusGroup,
    torrents,
    totalDownloadRate,
    totalUploadRate,
    wsConnected,
  } from '../lib/stores/queue.svelte';
  import { askConfirmation, pushToast } from '../lib/stores/ui.svelte';
  import type { QueueItem } from '../lib/api';

  interface QueueRow extends QueueItem {
    seeds?: number | null;
    created_at?: number | null;
    uploaded?: number | null;
    imdb_id?: string | null;
    tmdb_id?: number | null;
  }

  type FilterKey = 'all' | 'active' | 'seeding' | 'paused';

  const FILTERS: Array<{ key: FilterKey; label: string }> = [
    { key: 'all', label: 'All' },
    { key: 'active', label: 'Active' },
    { key: 'seeding', label: 'Seeding' },
    { key: 'paused', label: 'Paused' },
  ];

  let activeFilter = $state<FilterKey>('all');
  let magnet = $state('');
  let importing = $state(false);
  let addingMagnet = $state(false);

  const rows = $derived(torrents().map((item) => item as QueueRow));
  const visibleRows = $derived(
    activeFilter === 'all' ? rows : rows.filter((row) => statusGroup(row) === activeFilter),
  );
  const wsLive = $derived(wsConnected());
  const overallProgress = $derived(
    rows.length === 0 ? 0 : Math.round(rows.reduce((sum, row) => sum + row.progress, 0) / rows.length),
  );

  const counts = $derived({
    all: rows.length,
    active: rows.filter((row) => statusGroup(row) === 'active').length,
    seeding: rows.filter((row) => statusGroup(row) === 'seeding').length,
    paused: rows.filter((row) => statusGroup(row) === 'paused').length,
  });

  const addedLabel = (createdAt: number | null | undefined): string => {
    if (createdAt === null || createdAt === undefined) return '—';
    const stamp = new Date(Number(createdAt) * 1000);
    const pad = (value: number): string => String(value).padStart(2, '0');
    return `${stamp.getUTCFullYear()}-${pad(stamp.getUTCMonth() + 1)}-${pad(stamp.getUTCDate())} ${pad(stamp.getUTCHours())}:${pad(stamp.getUTCMinutes())}`;
  };

  function rowLink(row: QueueRow): string | null {
    if (row.imdb_id) return pathFor('movie', { imdbId: row.imdb_id });
    if (row.tmdb_id) return pathFor('tvshow', { showId: String(row.tmdb_id) });
    return null;
  }

  function openMatch(row: QueueRow): void {
    const link = rowLink(row);
    navigate(link === null ? pathFor('library', { q: row.name }) : link);
  }

  function onNameClick(row: QueueRow): (event: MouseEvent) => void {
    return (event) => {
      event.preventDefault();
      event.stopPropagation();
      openMatch(row);
    };
  }

  function onRowKey(row: QueueRow): (event: KeyboardEvent) => void {
    return (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openMatch(row);
      }
    };
  }

  function stopThen(run: () => void): (event: MouseEvent) => void {
    return (event) => {
      event.stopPropagation();
      run();
    };
  }

  function barTone(row: QueueRow): string {
    const group = statusGroup(row);
    if (group === 'seeding') return 'bg-emerald-500';
    if (group === 'paused') return 'bg-amber-500';
    if (row.status_code < 0) return 'bg-rose-500';
    return 'bg-indigo-500';
  }

  function groupDotTone(row: QueueRow): string {
    const group = statusGroup(row);
    if (group === 'seeding') return 'bg-emerald-400';
    if (group === 'paused') return 'bg-amber-400';
    if (row.status_code < 0) return 'bg-rose-400';
    return 'bg-indigo-400';
  }

  async function actOn(row: QueueRow, action: string): Promise<void> {
    try {
      await api.queueAction(row.id, action);
      await refreshFromRest();
    } catch (failure) {
      pushToast({
        message: `Queue action failed: ${failure instanceof ApiError ? failure.detail : String(failure)}`,
        kind: 'error',
      });
    }
  }

  async function submitMagnet(): Promise<void> {
    const value = magnet.trim();
    if (!value || addingMagnet) return;
    addingMagnet = true;
    try {
      await api.downloadMagnet(value);
      magnet = '';
      pushToast({ message: 'Magnet link queued for download', kind: 'success' });
      await refreshFromRest();
    } catch (failure) {
      pushToast({
        message: `Could not add magnet: ${failure instanceof ApiError ? failure.detail : String(failure)}`,
        kind: 'error',
      });
    } finally {
      addingMagnet = false;
    }
  }

  function onMagnetSubmit(event: SubmitEvent): void {
    event.preventDefault();
    void submitMagnet();
  }

  async function runImport(): Promise<void> {
    if (importing) return;
    importing = true;
    try {
      const res = await api.importNow();
      const count = res?.imported_count ?? '0';
      pushToast({ message: `Library import scan finished (${count} imported)`, kind: 'success' });
      await refreshFromRest();
    } catch (failure) {
      pushToast({
        message: `Import failed: ${failure instanceof ApiError ? failure.detail : String(failure)}`,
        kind: 'error',
      });
    } finally {
      importing = false;
    }
  }

  async function deleteTorrent(row: QueueRow): Promise<void> {
    const approved = await askConfirmation({
      id: 'cancelDownload',
      title: 'Cancel download',
      message: `Remove "${row.name}" from the queue?`,
      kind: 'danger',
      confirmLabel: 'Remove',
    });
    if (!approved) return;
    try {
      await api.removeTorrent(row.id, true);
      pushToast({ message: `Removed "${row.name}" from queue`, kind: 'info' });
    } catch (failure) {
      pushToast({
        message: `Could not remove torrent: ${failure instanceof ApiError ? failure.detail : String(failure)}`,
        kind: 'error',
      });
    }
    await refreshFromRest();
  }

  const socketState = $state({ opened: false });
  $effect(() => {
    if (!socketState.opened) {
      socketState.opened = true;
      openSocket();
    }
  });
</script>

<div class="flex flex-col gap-6" data-testid="queue-page">
  <!-- Summary Header Card -->
  <header
    class="rounded-2xl p-5 bg-onyx-surface border border-onyx-border/80 shadow-lg shadow-black/30 space-y-4"
    data-testid="queue-header"
  >
    <div class="flex flex-wrap items-center justify-between gap-4">
      <div>
        <h1 class="text-2xl font-black text-white tracking-tight">Download Queue</h1>
        <div class="mt-1.5 flex flex-wrap items-center gap-3 text-xs">
          <span
            class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-medium {wsLive
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
              : 'bg-amber-500/10 border-amber-500/30 text-amber-300'}"
            data-testid="queue-connection"
            data-connected={wsLive}
          >
            <span class="w-1.5 h-1.5 rounded-full {wsLive ? 'bg-emerald-400' : 'bg-amber-400'}" aria-hidden="true"></span>
            <span data-testid="queue-connection-label">{wsLive ? 'Live over /ws/queue' : 'REST refresh fallback'}</span>
          </span>
          <span class="text-slate-300 font-semibold font-mono" data-testid="queue-count">{rows.length} torrents</span>
        </div>
      </div>

      <div class="flex items-center gap-4 text-xs font-mono">
        <div class="rounded-xl bg-onyx-obsidian/80 border border-onyx-border/80 px-3.5 py-2 flex items-center gap-2">
          <span class="text-indigo-400 font-bold">↓</span>
          <span class="text-white font-semibold" data-testid="queue-total-rate">{formatSpeed(totalDownloadRate())}</span>
        </div>
        <div class="rounded-xl bg-onyx-obsidian/80 border border-onyx-border/80 px-3.5 py-2 flex items-center gap-2">
          <span class="text-emerald-400 font-bold">↑</span>
          <span class="text-slate-200 font-semibold">{formatSpeed(totalUploadRate())}</span>
        </div>
      </div>
    </div>

    <!-- Overall progress bar -->
    <div class="space-y-1.5">
      <div class="flex items-center justify-between text-[11px] text-slate-400 font-mono">
        <span>Overall queue progress</span>
        <span>{overallProgress}%</span>
      </div>
      <div class="w-full h-2 rounded-full bg-onyx-obsidian overflow-hidden border border-onyx-border/60" data-testid="queue-overall-progress">
        <div
          class="block h-full rounded-full bg-gradient-to-r from-indigo-500 to-emerald-400 transition-[width] duration-300"
          style={`width: ${overallProgress}%`}
          data-testid="queue-overall-progress-fill"
          data-progress={overallProgress}
        ></div>
      </div>
    </div>

    {#if backendDown()}
      <div
        class="flex flex-wrap items-center justify-between gap-3 rounded-xl px-4 py-2.5 bg-amber-950/50 border border-amber-700/50 text-amber-200 text-xs"
        role="status"
        aria-live="polite"
        data-testid="queue-outage"
      >
        <span data-testid="retry-countdown" data-retry-ms={retryDelayMs()}>
          {formatEta(retryDelayMs() / 1000)} until the next queue retry — data may be stale
        </span>
        <button
          class="rounded-lg px-3 py-1 bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-100 font-semibold cursor-pointer"
          type="button"
          data-testid="queue-retry-now"
          onclick={async () => {
            await retryNow();
          }}
        >
          Retry now
        </button>
      </div>
    {/if}
  </header>

  <!-- Magnet Bar + Run Import -->
  <div
    class="rounded-2xl p-4 bg-onyx-surface border border-onyx-border/80 flex flex-col md:flex-row items-stretch md:items-center gap-3"
    data-testid="queue-controls"
  >
    <form class="flex-1 flex items-center gap-2" data-testid="magnet-bar" onsubmit={onMagnetSubmit}>
      <input
        class="flex-1 rounded-xl px-3.5 py-2.5 bg-onyx-obsidian border border-onyx-border text-xs sm:text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
        type="text"
        placeholder="Paste a magnet link or torrent URI…"
        aria-label="Magnet link"
        data-testid="magnet-input"
        bind:value={magnet}
      />
      <button
        class="rounded-xl px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs sm:text-sm font-semibold transition-colors whitespace-nowrap cursor-pointer"
        type="submit"
        data-testid="magnet-submit"
        disabled={magnet.trim() === '' || addingMagnet}
      >
        {addingMagnet ? 'Adding…' : 'Add magnet'}
      </button>
    </form>

    <button
      class="inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 bg-onyx-raised hover:bg-slate-700 disabled:opacity-60 border border-onyx-border text-slate-100 text-xs sm:text-sm font-semibold transition-colors whitespace-nowrap cursor-pointer"
      type="button"
      disabled={importing}
      data-testid="import-now"
      onclick={() => void runImport()}
    >
      {#if importing}
        <span class="w-3.5 h-3.5 rounded-full border-2 border-slate-200 border-t-transparent animate-spin" aria-hidden="true"></span>
      {/if}
      <span>Run Import Now</span>
    </button>
  </div>

  <!-- Status Filter Pills -->
  <div class="flex flex-wrap items-center gap-2" role="group" aria-label="Filter torrents by status" data-testid="queue-filter-pills">
    {#each FILTERS as filter}
      {@const active = activeFilter === filter.key}
      <button
        class="rounded-full px-3.5 py-1.5 text-xs font-semibold border transition-colors cursor-pointer {active
          ? 'bg-indigo-600 text-white border-indigo-500 shadow-sm shadow-indigo-950/50'
          : 'bg-onyx-surface text-slate-300 border-onyx-border hover:border-slate-500 hover:text-white'}"
        type="button"
        data-testid="queue-filter-pill"
        data-filter={filter.key}
        data-active={active}
        aria-pressed={active}
        onclick={() => (activeFilter = filter.key)}
      >{filter.label}</button>
    {/each}
    <span class="ml-auto text-xs text-slate-500 font-mono">
      {counts.active} active · {counts.seeding} seeding · {counts.paused} paused
    </span>
  </div>

  <!-- Torrent Rows -->
  <div class="flex flex-col gap-3" data-testid="queue-list" aria-live="polite">
    {#each visibleRows as row (String(row.id))}
      {@const clamped = Math.min(100, Math.max(0, row.progress))}
      <div
        class="rounded-2xl p-4 sm:p-5 bg-onyx-surface hover:bg-onyx-raised/45 border border-onyx-border/80 hover:border-slate-600 transition-colors cursor-pointer space-y-3"
        data-testid="queue-row"
        data-id={String(row.id)}
        data-group={statusGroup(row)}
        role="button"
        tabindex="0"
        onclick={() => openMatch(row)}
        onkeydown={onRowKey(row)}
      >
        <div class="flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div class="flex items-center gap-2.5 min-w-0 flex-1">
            <span class="w-2.5 h-2.5 rounded-full shrink-0 {groupDotTone(row)}" aria-hidden="true"></span>
            <a
              class="text-sm sm:text-base font-semibold text-white hover:text-indigo-300 truncate transition-colors"
              href={rowLink(row)}
              data-testid="queue-name"
              onclick={onNameClick(row)}
            >{row.name}</a>
          </div>

          <div class="flex flex-wrap items-center gap-1.5 shrink-0">
            <button
              class="w-8 h-8 rounded-lg bg-onyx-obsidian hover:bg-slate-700 border border-onyx-border text-slate-300 hover:text-white text-xs font-bold flex items-center justify-center transition-colors cursor-pointer"
              type="button"
              title="Increase priority"
              data-testid="priority-up"
              onclick={stopThen(() => void actOn(row, 'priority/up'))}
            >↑</button>
            <button
              class="w-8 h-8 rounded-lg bg-onyx-obsidian hover:bg-slate-700 border border-onyx-border text-slate-300 hover:text-white text-xs font-bold flex items-center justify-center transition-colors cursor-pointer"
              type="button"
              title="Decrease priority"
              data-testid="priority-down"
              onclick={stopThen(() => void actOn(row, 'priority/down'))}
            >↓</button>
            {#if statusGroup(row) === 'paused'}
              <button
                class="rounded-lg px-3 py-1.5 bg-emerald-500/15 hover:bg-emerald-600 border border-emerald-500/35 text-emerald-300 hover:text-white text-xs font-semibold transition-colors cursor-pointer"
                type="button"
                data-testid="queue-resume"
                onclick={stopThen(() => void actOn(row, 'resume'))}
              >Resume</button>
            {:else}
              <button
                class="rounded-lg px-3 py-1.5 bg-amber-500/15 hover:bg-amber-600 border border-amber-500/35 text-amber-300 hover:text-white text-xs font-semibold transition-colors cursor-pointer"
                type="button"
                data-testid="queue-pause"
                onclick={stopThen(() => void actOn(row, 'pause'))}
              >Pause</button>
            {/if}
            <button
              class="rounded-lg px-3 py-1.5 bg-rose-500/10 hover:bg-rose-600 border border-rose-500/35 text-rose-300 hover:text-white text-xs font-semibold transition-colors cursor-pointer"
              type="button"
              data-testid="delete-torrent"
              onclick={stopThen(() => void deleteTorrent(row))}
            >Cancel + delete</button>
          </div>
        </div>

        <!-- Visible Progress Bar -->
        <div class="flex items-center gap-3">
          <div class="flex-1 h-2 rounded-full bg-onyx-obsidian overflow-hidden border border-onyx-border/60" data-testid="queue-progress-track">
            <div
              class="block h-full rounded-full transition-[width] duration-300 {barTone(row)}"
              style={`width: ${clamped}%`}
              data-testid="progress_percent"
              data-progress={row.progress}
            ></div>
          </div>
          <span class="w-12 text-right text-xs font-mono font-semibold text-slate-300 tabular-nums">
            {clamped}%
          </span>
        </div>

        <!-- Transfer Stats Strip -->
        <div class="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-xs font-mono text-slate-400">
          <span>Size <strong class="text-slate-200 font-medium" data-testid="queue-size">{formatBytes(row.total_size)}</strong></span>
          <span>Speed <strong class="text-indigo-300 font-medium" data-testid="queue-download-rate">{formatSpeed(row.rate_download)}</strong></span>
          <span>Transferred <strong class="text-slate-200 font-medium" data-testid="queue-uploaded">{formatBytes(Number(row.uploaded ?? (row.progress / 100) * row.total_size))}</strong></span>
          <span>ETA <strong class="text-slate-200 font-medium" data-testid="queue-eta">{formatEta(row.eta)}</strong></span>
          <span>Seeds <strong class="text-emerald-400 font-medium" data-testid="queue-seeds">{row.seeds ?? 0}</strong></span>
          <span class="ml-auto text-slate-500" data-testid="queue-added">{addedLabel(row.created_at)}</span>
        </div>
      </div>
    {:else}
      <div class="rounded-2xl py-16 px-6 bg-onyx-surface/70 border border-onyx-border text-center text-sm text-slate-400" data-testid="queue-empty">
        No torrents match this filter.
      </div>
    {/each}
  </div>
</div>
