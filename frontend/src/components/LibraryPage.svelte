<!-- /library: poster-card Media Library browser with instant local search,
     category/state filters, Title/Year/Size sorting, click-through to detail
     pages, Rescan Library, and isolated per-card management actions. -->
<script lang="ts">
  import { api, ApiError, formatBytes, libraryBadgeLabel } from '../lib/api';
  import { navigate, pathFor, route } from '../lib/router.svelte';
  import { askConfirmation, pushToast } from '../lib/stores/ui.svelte';
  import {
    isCached,
    libraryCount,
    movies,
    refresh,
    seededTitles,
    shows,
  } from '../lib/stores/library.svelte';
  import type { LibraryMovie, LibraryShow } from '../lib/api';

  type FilterKey = 'all' | 'movies' | 'tv' | 'seeding';
  type SortKey = 'title' | 'year' | 'size';
  type LibraryAction = 'remove-seed' | 'track' | 'untrack' | 'delete';

  interface LibraryRow {
    key: string;
    kind: 'movie' | 'tv';
    name: string;
    title: string;
    year: number | null;
    imdb_id: string | null;
    tmdb_id: number | null;
    seeded: boolean;
    tracked: boolean;
    missingCount: number;
    sizeMb: number;
    detail: string;
    badge: string | null;
    poster: string;
    link: string | null;
  }

  function movieRow(item: LibraryMovie): LibraryRow {
    return {
      key: `movie:${item.path || item.name}`,
      kind: 'movie',
      name: item.name,
      title: item.title || item.name,
      year: item.year,
      imdb_id: item.imdb_id,
      tmdb_id: null,
      seeded: item.seeding,
      tracked: false,
      missingCount: 0,
      sizeMb: item.size_mb,
      detail: `${item.file_count} files · ${formatBytes(item.size_mb * 1_000_000)}`,
      badge: libraryBadgeLabel(item.seeding ? 'available' : null),
      poster: item.poster || '',
      link: item.imdb_id ? pathFor('movie', { imdbId: item.imdb_id }) : null,
    };
  }

  function showRow(item: LibraryShow): LibraryRow {
    return {
      key: `tv:${item.path || item.name}`,
      kind: 'tv',
      name: item.name,
      title: item.title || item.name,
      year: item.year,
      imdb_id: null,
      tmdb_id: item.tmdb_id,
      seeded: item.seeding,
      tracked: item.monitored,
      missingCount: item.missing.length,
      sizeMb: 0,
      detail: `${item.seasons_count} seasons · ${item.episodes_count} episodes · ${item.missing.length} missing`,
      badge: libraryBadgeLabel(item.monitored ? 'monitored' : null),
      poster: item.poster || '',
      link: item.tmdb_id ? pathFor('tvshow', { showId: String(item.tmdb_id) }) : null,
    };
  }

  const FILTERS: Array<{ key: FilterKey; label: string }> = [
    { key: 'all', label: 'All' },
    { key: 'movies', label: 'Movies' },
    { key: 'tv', label: 'TV Shows' },
    { key: 'seeding', label: 'Seeding' },
  ];

  const SORTS: Array<{ key: SortKey; label: string }> = [
    { key: 'title', label: 'Title' },
    { key: 'year', label: 'Year' },
    { key: 'size', label: 'Size' },
  ];

  const pageState = $state({
    filter: 'all' as FilterKey,
    sort: 'title' as SortKey,
    pending: null as Promise<void> | null,
    scanning: false,
    failed: false,
    brokenPosters: {} as Record<string, boolean>,
  });

  $effect(() => {
    if (pageState.pending === null) {
      pageState.pending = refresh().then(
        () => void (pageState.failed = false),
        () => void (pageState.failed = true),
      );
    }
  });

  const allRows = $derived([...movies().map(movieRow), ...shows().map(showRow)]);
  const searchQuery = $derived(route()?.params?.q ?? '');

  function matchesFilter(row: LibraryRow): boolean {
    if (pageState.filter === 'movies') return row.kind === 'movie';
    if (pageState.filter === 'tv') return row.kind === 'tv';
    if (pageState.filter === 'seeding') return row.seeded;
    return true;
  }

  function matchesSearch(row: LibraryRow): boolean {
    const needle = searchQuery.trim().toLowerCase();
    return needle === '' || row.title.toLowerCase().includes(needle) || row.name.toLowerCase().includes(needle);
  }

  function compareRows(a: LibraryRow, b: LibraryRow): number {
    if (pageState.sort === 'year') {
      return (b.year ?? -1) - (a.year ?? -1) || a.title.localeCompare(b.title);
    }
    if (pageState.sort === 'size') {
      return b.sizeMb - a.sizeMb || a.title.localeCompare(b.title);
    }
    return a.title.localeCompare(b.title);
  }

  const visibleRows = $derived(
    allRows.filter((row) => matchesFilter(row) && matchesSearch(row)).sort(compareRows),
  );

  function onSearchInput(event: Event): void {
    const input = event.currentTarget as HTMLInputElement;
    navigate(pathFor('library', { q: input.value }));
  }

  function preventLinkDefault(event: MouseEvent): void {
    event.preventDefault();
  }

  function openCard(row: LibraryRow): void {
    if (row.link !== null) navigate(row.link);
  }

  function openCardOnKey(row: LibraryRow, event: KeyboardEvent): void {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openCard(row);
    }
  }

  function initialsOf(title: string): string {
    return title
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0]?.toUpperCase() ?? '')
      .join('');
  }

  async function rescanLibrary(): Promise<void> {
    if (pageState.scanning) return;
    pageState.scanning = true;
    try {
      await refresh();
      pageState.failed = false;
      pushToast({ message: `Library rescanned (${libraryCount()} titles)`, kind: 'success' });
    } catch (failure) {
      pageState.failed = true;
      pushToast({
        message: `Rescan failed: ${failure instanceof ApiError ? failure.detail : String(failure)}`,
        kind: 'error',
      });
    } finally {
      pageState.scanning = false;
    }
  }

  async function runAction(row: LibraryRow, action: LibraryAction, confirm = false): Promise<void> {
    try {
      await api.libraryAction(action, row.kind, row.name, confirm);
      await refresh();
      pageState.failed = false;
      if (action === 'remove-seed') pushToast({ message: `Stopped seeding ${row.title}`, kind: 'info' });
      else if (action === 'track') pushToast({ message: `Now tracking ${row.title}`, kind: 'success' });
      else if (action === 'untrack') pushToast({ message: `Stopped tracking ${row.title}`, kind: 'info' });
      else if (action === 'delete') pushToast({ message: `Deleted ${row.title} from library`, kind: 'info' });
    } catch (failure) {
      pageState.failed = true;
      pushToast({
        message: `Action failed: ${failure instanceof ApiError ? failure.detail : String(failure)}`,
        kind: 'error',
      });
    }
  }

  function stopSeeding(row: LibraryRow, event: MouseEvent): void {
    event.stopPropagation();
    void runAction(row, 'remove-seed');
  }

  function toggleTrack(row: LibraryRow, event: MouseEvent): void {
    event.stopPropagation();
    void runAction(row, row.tracked ? 'untrack' : 'track');
  }

  async function deleteEntry(row: LibraryRow, event: MouseEvent): Promise<void> {
    event.stopPropagation();
    const approved = await askConfirmation({
      id: `libraryDelete:${row.kind}:${row.name}`,
      title: 'Delete library title',
      message: `Delete "${row.title}" and its files from the library? This cannot be undone.`,
      kind: 'danger',
      confirmLabel: 'Delete',
    });
    if (!approved) return;
    await runAction(row, 'delete', true);
  }
</script>

<div class="flex flex-col gap-6" data-testid="library-page">
  <!-- Header -->
  <header
    class="rounded-2xl p-5 bg-onyx-surface border border-onyx-border/80 flex flex-wrap items-center justify-between gap-4 shadow-lg shadow-black/30"
    data-testid="library-header"
  >
    <div>
      <h1 class="text-2xl font-black text-white tracking-tight">Media Library</h1>
      <div class="mt-1.5 flex items-center gap-3 text-xs">
        <span class="font-semibold text-slate-200 font-mono" data-testid="library-count">{libraryCount()} titles</span>
        <span class="text-slate-600">•</span>
        <span class="text-sky-300 font-mono" data-testid="library-seeded">{seededTitles()} seeded</span>
      </div>
    </div>

    <button
      class="inline-flex items-center gap-2 rounded-xl px-4 py-2.5 bg-indigo-600/20 hover:bg-indigo-600 disabled:opacity-60 border border-indigo-500/35 hover:border-indigo-500 text-indigo-300 hover:text-white text-xs sm:text-sm font-semibold transition-colors cursor-pointer"
      type="button"
      disabled={pageState.scanning}
      data-testid="rescan-library"
      onclick={() => void rescanLibrary()}
    >
      {#if pageState.scanning}
        <span class="w-3.5 h-3.5 rounded-full border-2 border-current border-t-transparent animate-spin" aria-hidden="true"></span>
      {/if}
      <span>Rescan Library</span>
    </button>
  </header>

  <!-- Search + Filter Pills + Sort -->
  <div class="flex flex-wrap items-center justify-between gap-3" data-testid="library-controls">
    <div class="flex flex-wrap items-center gap-3 flex-1 min-w-0">
      <div class="relative w-full sm:w-64">
        <svg aria-hidden="true" class="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-4.35-4.35M17 11a6 6 0 11-12 0 6 6 0 0112 0z" />
        </svg>
        <input
          class="w-full rounded-xl pl-9 pr-3 py-2 bg-onyx-surface border border-onyx-border text-xs sm:text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
          type="search"
          name="q"
          placeholder="Filter library…"
          value={searchQuery}
          oninput={onSearchInput}
          data-testid="library-search-input"
        />
      </div>

      <nav
        class="inline-flex flex-wrap items-center gap-1.5 p-1 rounded-xl bg-onyx-surface border border-onyx-border"
        data-testid="library-tabs"
        data-active={pageState.filter}
        aria-label="Library filters"
      >
        {#each FILTERS as filterItem}
          {@const active = pageState.filter === filterItem.key}
          <button
            class="rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer {active
              ? 'bg-indigo-600 text-white shadow-sm'
              : 'text-slate-400 hover:text-white'}"
            type="button"
            data-testid="library-filter-pill"
            data-filter={filterItem.key}
            data-active={active}
            onclick={() => (pageState.filter = filterItem.key)}
          >{filterItem.label}</button>
        {/each}
      </nav>
    </div>

    <label class="flex items-center gap-2 text-xs text-slate-400" data-testid="library-sort-label">
      <span>Sort</span>
      <select
        class="rounded-xl px-3 py-2 bg-onyx-surface border border-onyx-border text-xs font-medium text-white focus:outline-none focus:border-indigo-500 cursor-pointer"
        data-testid="library-sort"
        bind:value={pageState.sort}
      >
        {#each SORTS as sortItem}
          <option value={sortItem.key}>{sortItem.label}</option>
        {/each}
      </select>
    </label>
  </div>

  {#if pageState.failed && !isCached()}
    <div
      class="rounded-xl px-4 py-3 bg-amber-950/40 border border-amber-700/50 text-amber-200 text-xs sm:text-sm"
      role="status"
      aria-live="polite"
      data-testid="library-error"
    >
      <span data-testid="library-error-message">Library scan failed — try clicking Rescan Library.</span>
    </div>
  {/if}

  <!-- Poster Card Grid -->
  <section
    class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4 sm:gap-5"
    data-testid="library-rows"
  >
    {#if visibleRows.length === 0}
      <div class="col-span-full rounded-2xl py-16 px-6 bg-onyx-surface/70 border border-onyx-border text-center text-sm text-slate-400">
        {searchQuery ? `No library titles match “${searchQuery}”.` : 'Nothing matches these filters yet.'}
      </div>
    {/if}

    {#each visibleRows as row (row.key)}
      {@const showPoster = Boolean(row.poster) && !pageState.brokenPosters[row.key]}
      <div
        class="group rounded-2xl overflow-hidden bg-onyx-surface border border-onyx-border/80 flex flex-col shadow-md shadow-black/40 transition-colors {row.link
          ? 'cursor-pointer hover:border-indigo-500/80'
          : 'cursor-default'}"
        data-testid="library-row"
        data-kind={row.kind}
        data-seeded={row.seeded}
        data-title={row.title}
        role="button"
        tabindex="0"
        aria-label={`Open ${row.title}`}
        onclick={() => openCard(row)}
        onkeydown={openCardOnKey.bind(null, row)}
      >
        <!-- Cover artwork -->
        <div class="relative w-full aspect-[2/3] bg-onyx-raised overflow-hidden">
          {#if showPoster}
            <img
              class="w-full h-full object-cover {row.link ? 'poster-zoom' : ''}"
              src={row.poster}
              alt={`Cover for ${row.title}`}
              loading="lazy"
              onerror={() => (pageState.brokenPosters = { ...pageState.brokenPosters, [row.key]: true })}
            />
          {:else}
            <div class="w-full h-full bg-gradient-to-br from-slate-800 via-onyx-surface to-indigo-950/60 flex flex-col items-center justify-center p-4 text-center gap-1.5">
              <span class="text-2xl font-black tracking-wider text-slate-500/80">{initialsOf(row.title) || '?'}</span>
              <span class="text-[11px] font-medium text-slate-400 line-clamp-3">{row.title}</span>
            </div>
          {/if}

          <div class="pointer-events-none absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-black/80 via-black/30 to-transparent" aria-hidden="true"></div>

          {#if row.year}
            <span
              class="absolute top-2 right-2 rounded-md bg-black/75 backdrop-blur-sm border border-white/10 px-1.5 py-0.5 text-[10px] font-bold font-mono text-white"
              data-testid="library-year"
            >{row.year}</span>
          {/if}

          <span class="absolute top-2 left-2 rounded-md bg-black/70 backdrop-blur-sm border border-white/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-slate-300">
            {row.kind === 'tv' ? 'TV' : 'Movie'}
          </span>

          <div class="absolute bottom-2 left-2 right-2 flex flex-wrap gap-1">
            {#if row.badge}
              <span
                class="inline-flex items-center rounded-md bg-emerald-500/20 border border-emerald-500/40 backdrop-blur-sm px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-emerald-200"
                data-testid="library-badge"
              >{row.badge}</span>
            {/if}
            {#if row.seeded}
              <span class="inline-flex items-center rounded-md bg-sky-500/25 border border-sky-400/40 backdrop-blur-sm px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-sky-200">
                Seeding
              </span>
            {/if}
            {#if row.missingCount > 0}
              <span class="inline-flex items-center rounded-md bg-amber-500/25 border border-amber-400/40 backdrop-blur-sm px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-amber-200">
                {row.missingCount} missing
              </span>
            {/if}
          </div>
        </div>

        <!-- Metadata + Isolated Actions -->
        <div class="p-3.5 flex-1 flex flex-col justify-between gap-3">
          <div class="min-w-0 space-y-1">
            <h2
              class="text-xs sm:text-sm font-bold text-white leading-snug line-clamp-2 {row.link ? 'group-hover:text-indigo-300 transition-colors' : ''}"
              data-testid="library-title"
              title={row.title}
            >
              {#if row.link}
                <a class="text-inherit" href={row.link} data-testid="library-link" onclick={preventLinkDefault}>{row.title}</a>
              {:else}
                <span data-testid="library-title-plain">{row.title}</span>
              {/if}
            </h2>
            <p class="text-[11px] text-slate-400 line-clamp-2" data-testid="library-detail">{row.detail}</p>
            {#if !row.link}
              <span class="sr-only" data-testid="library-no-action">Unmatched disk entry</span>
            {/if}
          </div>

          <div class="flex flex-wrap items-center gap-1.5 pt-2 border-t border-onyx-border/60">
            {#if row.kind === 'tv' && row.name}
              <button
                class="flex-1 rounded-lg px-2 py-1.5 text-[11px] font-semibold transition-colors cursor-pointer {row.tracked
                  ? 'bg-indigo-500/15 hover:bg-indigo-600 border border-indigo-500/35 text-indigo-300 hover:text-white'
                  : 'bg-indigo-600 hover:bg-indigo-500 text-white'}"
                type="button"
                data-testid="track-toggle"
                onclick={toggleTrack.bind(null, row)}
              >{row.tracked ? 'Untrack' : 'Track'}</button>
            {/if}
            {#if row.seeded}
              <button
                class="flex-1 rounded-lg px-2 py-1.5 bg-sky-500/15 hover:bg-sky-600 border border-sky-500/35 text-sky-300 hover:text-white text-[11px] font-semibold transition-colors whitespace-nowrap cursor-pointer"
                type="button"
                data-testid="stop-seeding"
                onclick={stopSeeding.bind(null, row)}
              >Stop seeding</button>
            {/if}
            <button
              class="flex-1 rounded-lg px-2 py-1.5 bg-rose-500/10 hover:bg-rose-600 border border-rose-500/35 text-rose-300 hover:text-white text-[11px] font-semibold transition-colors cursor-pointer"
              type="button"
              data-testid="delete-library"
              onclick={deleteEntry.bind(null, row)}
            >Delete</button>
          </div>
        </div>
      </div>
    {/each}
  </section>
</div>
