<!-- TV detail page (/tv/:showId): cinematic hero backdrop, Monitor toggle,
     season selector tabs, full-height episode catalog with availability pills,
     season-pack Download Best + Release Drawer, and More Like This rail. -->
<script lang="ts">
  import MediaRail from './MediaRail.svelte';
  import ReleaseDrawer from './ReleaseDrawer.svelte';
  import { ApiError, api, bestRelease, isDuplicateDownload, libraryBadgeLabel, libraryBadgeTone } from '../lib/api';
  import type { ReleaseItem, TvDetails } from '../lib/api';
  import { route } from '../lib/router.svelte';
  import { askConfirmation, closeDrawer, drawer, openDrawer, pushToast, setDrawerReleases } from '../lib/stores/ui.svelte';

  const page = $state({
    details: null as TvDetails | null,
    error: null as string | null,
    monitored: false,
    monitoredSeriesId: null as number | null,
    activeSeason: null as number | null,
    downloadingBest: false,
    posterBroken: false,
  });

  let requestedId: number | null = null;
  let pending: Promise<unknown> | null = null;

  const match = $derived(route());
  const showId = $derived(
    match && match.view === 'tvshow' ? Number(match.params.showId ?? '') : Number('invalid'),
  );

  $effect(() => ensureLoaded());

  function ensureLoaded(): void {
    const id = showId;
    if (!Number.isFinite(id)) return;
    if (requestedId !== id) {
      requestedId = id;
      pending = null;
      page.details = null;
      page.error = null;
      page.posterBroken = false;
      page.monitoredSeriesId = null;
      closeDrawer();
    }
    if (pending === null) pending = loadShow(id);
  }

  async function loadShow(id: number): Promise<void> {
    try {
      const details = await api.tvDetails(id);
      pending = null;
      if (requestedId !== id) return;
      page.details = details;
      page.error = null;
      page.monitored = details.monitored;
      page.activeSeason = details.seasons.length > 0 ? details.seasons[0].season_number : null;
    } catch (failure) {
      pending = null;
      if (requestedId !== id) return;
      page.details = null;
      page.error = failure instanceof ApiError ? String(failure.detail) : String(failure);
    }
  }

  const details = $derived(page.details);
  const seasons = $derived(details?.seasons ?? []);
  const activeSeason = $derived(page.activeSeason);
  const monitorLabel = $derived(page.monitored ? 'Unmonitor' : '+ Monitor');
  const monitorChip = $derived(page.monitored ? 'Monitoring' : 'Unmonitored');

  function seasonRows(): Array<{ season_number: number; count: number; onSelect: () => void }> {
    return seasons.map((season) => {
      const number = Number(season.season_number);
      return {
        season_number: number,
        count: season.episodes.length,
        onSelect: () => (page.activeSeason = number),
      };
    });
  }

  function episodeRows(): Array<{
    episode_number: number;
    name: string;
    air_date: string | null;
    available: boolean;
    onReleases: () => void;
  }> {
    const season = seasons.find((row) => Number(row.season_number) === activeSeason);
    if (!season) return [];
    return season.episodes.map((episode) => {
      const number = Number(episode.episode_number ?? 0);
      return {
        episode_number: number,
        name: String(episode.name ?? ''),
        air_date: (episode.air_date ?? null) as string | null,
        available: episode.available === true,
        onReleases: () => void openEpisodeDrawer(number),
      };
    });
  }

  function toggleMonitor(): void {
    const show = page.details;
    if (!show) return;
    if (page.monitored) {
      page.monitored = false;
      const targetId = page.monitoredSeriesId ?? Number(show.id);
      void api.unmonitorSeries(targetId)
        .then(() => {
          page.monitoredSeriesId = null;
          pushToast({ message: `Stopped monitoring ${show.title}`, kind: 'info' });
        })
        .catch(() => {
          page.monitored = true;
          pushToast({ message: `Unmonitor request failed for ${show.title}`, kind: 'error' });
        });
      return;
    }
    page.monitored = true;
    void api.monitorSeries({
      tmdb_id: show.id,
      title: show.title,
      imdb_id: show.imdb_id,
      status: show.status ?? 'Returning Series',
    })
      .then((res) => {
        if (res && typeof res.id === 'number') page.monitoredSeriesId = res.id;
        pushToast({ message: `Now monitoring ${show.title}`, kind: 'success' });
      })
      .catch(() => {
        page.monitored = false;
        pushToast({ message: `Monitor request failed for ${show.title}`, kind: 'error' });
      });
  }

  async function downloadBestSeason(): Promise<void> {
    const show = page.details;
    const season = page.activeSeason;
    if (!show || season === null || page.downloadingBest) return;
    page.downloadingBest = true;
    try {
      const releases = await api.releasesTv(show.title, season);
      const best = bestRelease(releases);
      if (!best) {
        pushToast({ message: `No releases found for ${show.title} season ${season}`, kind: 'info' });
        return;
      }
      const target = { media_type: 'tv', display_title: show.title, season, tmdb_id: show.id };
      try {
        await api.downloadRelease(best, target, false);
        pushToast({
          message: `Queued ${best.title} for ${show.title} season ${season}`,
          kind: 'success',
        });
      } catch (failure) {
        if (!isDuplicateDownload(failure)) {
          pushToast({ message: `Could not queue season ${season}: ${failure instanceof ApiError ? failure.detail : String(failure)}`, kind: 'error' });
          return;
        }
        const approved = await askConfirmation({
          id: `tv-season-${show.id}-${season}`,
          title: 'Already in library',
          message: `${show.title} Season ${season} already has files in your library. Download again?`,
          kind: 'duplicate',
          confirmLabel: 'Download again',
        });
        if (!approved) return;
        await api.downloadRelease(best, target, true);
        pushToast({
          message: `Queued ${best.title} again`,
          kind: 'success',
          actionLabel: 'Open queue',
          actionPath: '/queue',
        });
      }
    } catch (failure) {
      pushToast({ message: `Could not fetch releases: ${failure instanceof ApiError ? failure.detail : String(failure)}`, kind: 'error' });
    } finally {
      page.downloadingBest = false;
    }
  }

  async function openSeasonPacks(): Promise<void> {
    const show = page.details;
    const season = page.activeSeason;
    if (!show || season === null) return;
    openDrawer('tv-season', { media_type: 'tv', season, tmdb_id: show.id, display_title: show.title }, true);
    try {
      const releases = await api.releasesTv(show.title, season, undefined, true);
      setDrawerReleases(releases, false);
      if (releases.length === 0) {
        pushToast({ message: `No season packs found for ${show.title}`, kind: 'info' });
      }
    } catch {
      setDrawerReleases([], false);
    }
  }

  async function openEpisodeDrawer(episode: number): Promise<void> {
    const show = page.details;
    const season = page.activeSeason;
    if (!show || season === null) return;
    openDrawer('tv-episode', { media_type: 'tv', season, episode, tmdb_id: show.id, display_title: show.title }, true);
    try {
      const releases = await api.releasesTv(show.title, season, episode);
      setDrawerReleases(releases, false);
      if (releases.length === 0) {
        pushToast({ message: `No releases found for ${show.title} S${season}E${episode}`, kind: 'info' });
      }
    } catch {
      setDrawerReleases([], false);
    }
  }

  const drawerState = $derived(drawer());
  const drawerRows = $derived((drawerState?.releases ?? []) as ReleaseItem[]);
  const currentEpisodes = $derived(episodeRows());
  const availableCount = $derived(currentEpisodes.filter((ep) => ep.available).length);
</script>

<div class="flex flex-col gap-8" data-testid="tv-detail-page">
  {#if details}
    <!-- Cinematic Hero Card -->
    <section
      class="relative overflow-hidden rounded-2xl border border-onyx-border/80 bg-onyx-surface shadow-xl shadow-black/40"
      data-testid="tv-show-card"
    >
      {#if details.poster && !page.posterBroken}
        <img
          src={details.poster}
          alt=""
          aria-hidden="true"
          class="absolute inset-0 w-full h-full object-cover opacity-20 blur-2xl scale-110 pointer-events-none"
        />
      {/if}
      <div class="absolute inset-0 bg-gradient-to-r from-onyx-obsidian via-onyx-obsidian/92 to-onyx-obsidian/60 pointer-events-none"></div>

      <div class="relative p-5 sm:p-8 flex flex-col md:flex-row items-start gap-6 lg:gap-8">
        <!-- Portrait 2:3 Poster -->
        <div class="w-40 sm:w-48 md:w-52 shrink-0 aspect-[2/3] rounded-xl overflow-hidden bg-onyx-raised border border-white/10 shadow-2xl shadow-black/70">
          {#if details.poster && !page.posterBroken}
            <img
              class="w-full h-full object-cover"
              src={details.poster}
              alt={`Poster for ${details.title}`}
              loading="lazy"
              onerror={() => (page.posterBroken = true)}
            />
          {:else}
            <div class="w-full h-full bg-gradient-to-br from-slate-800 to-indigo-950/60 flex items-center justify-center p-4 text-center">
              <span class="text-2xl font-black text-slate-400">{details.title.slice(0, 2).toUpperCase()}</span>
            </div>
          {/if}
        </div>

        <!-- Show Info & Monitor Controls -->
        <div class="flex-1 min-w-0 flex flex-col justify-between gap-5">
          <div class="space-y-3.5">
            <div class="flex flex-wrap items-center gap-2">
              {#if details.rating !== null}
                <span class="rounded-md bg-amber-500/15 border border-amber-500/30 px-2 py-0.5 text-xs font-bold text-amber-300" data-testid="rating-badge">
                  ★ {details.rating}
                </span>
              {/if}
              {#if details.year}
                <span class="text-xs font-mono text-slate-300">{details.year}</span>
              {/if}
              {#if details.network}
                <span class="rounded-md bg-onyx-raised border border-onyx-border px-2 py-0.5 text-xs text-slate-300">{details.network}</span>
              {/if}
              {#if details.status}
                <span class="rounded-md bg-slate-800/80 border border-slate-700 px-2 py-0.5 text-xs text-slate-300">{details.status}</span>
              {/if}
              {#if details.library_status}
                <span
                  class="rounded-md border px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide {libraryBadgeTone(details.library_status)}"
                  data-testid="library-badge"
                  data-status={details.library_status}
                >
                  {libraryBadgeLabel(details.library_status)}
                </span>
              {/if}
            </div>

            <h1 class="text-2xl sm:text-3xl lg:text-4xl font-black text-white tracking-tight leading-tight">
              {details.title}
            </h1>

            {#if details.genres.length > 0}
              <div class="flex flex-wrap items-center gap-1.5" data-testid="genre-chips">
                {#each details.genres as genre}
                  <span class="rounded-full bg-onyx-raised/80 border border-onyx-border px-2.5 py-0.5 text-[11px] font-medium text-slate-300" data-testid="genre-chip">
                    {genre}
                  </span>
                {/each}
              </div>
            {/if}

            {#if details.overview}
              <p class="text-sm text-slate-300 leading-relaxed max-w-3xl">{details.overview}</p>
            {/if}
          </div>

          <div class="flex flex-wrap items-center gap-3 pt-1" data-testid="monitor-control">
            <button
              class="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-semibold transition-colors cursor-pointer {page.monitored
                ? 'bg-emerald-500/15 hover:bg-rose-500/20 border border-emerald-500/40 hover:border-rose-500/40 text-emerald-300 hover:text-rose-200'
                : 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-950/60'}"
              type="button"
              data-testid="monitor-toggle"
              onclick={toggleMonitor}
            >
              {monitorLabel}
            </button>
            <span
              class="rounded-lg px-2.5 py-1 text-xs font-semibold border {page.monitored
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                : 'bg-onyx-raised border-onyx-border text-slate-400'}"
              data-testid="monitor-status"
            >
              {monitorChip}
            </span>
          </div>
        </div>
      </div>
    </section>

    <!-- Seasons & Full-Height Episodes Browser -->
    {#if seasons.length > 0}
      <div class="space-y-4">
        <!-- Season selector pill bar -->
        <div class="flex items-center gap-2 overflow-x-auto no-scrollbar pb-1" data-testid="season-tabs" role="tablist" aria-label="Seasons">
          {#each seasonRows() as season}
            {@const active = season.season_number === activeSeason}
            <button
              class="shrink-0 rounded-xl px-4 py-2 text-xs sm:text-sm font-semibold border transition-colors cursor-pointer {active
                ? 'bg-indigo-600 text-white border-indigo-500 shadow-sm shadow-indigo-950/60'
                : 'bg-onyx-surface text-slate-300 border-onyx-border hover:border-slate-500 hover:text-white'}"
              type="button"
              role="tab"
              aria-selected={active}
              data-testid="season-tab"
              data-season={season.season_number}
              data-active={active}
              onclick={season.onSelect}
            >
              Season {season.season_number}
              <span class="ml-1.5 text-[11px] opacity-75 font-mono">({season.count})</span>
            </button>
          {/each}
        </div>

        {#if activeSeason !== null}
          <section
            class="rounded-2xl border border-onyx-border/80 bg-onyx-surface overflow-hidden shadow-lg shadow-black/30"
            data-testid="season-section"
            data-season={activeSeason}
          >
            <header
              class="px-5 py-4 border-b border-onyx-border/80 bg-onyx-obsidian/50 flex flex-wrap items-center justify-between gap-3"
              data-testid="season-header"
            >
              <div>
                <h2 class="text-base font-bold text-white">Season {activeSeason}</h2>
                <p class="text-xs text-slate-400 mt-0.5">
                  {currentEpisodes.length} episode{currentEpisodes.length === 1 ? '' : 's'}
                  {#if availableCount > 0}
                    <span class="text-emerald-400"> · {availableCount} on disk</span>
                  {/if}
                </p>
              </div>

              <div class="flex flex-wrap items-center gap-2">
                <button
                  class="rounded-xl px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-60 text-white text-xs font-semibold shadow-sm transition-colors cursor-pointer"
                  type="button"
                  disabled={page.downloadingBest}
                  data-testid="download-best"
                  onclick={() => void downloadBestSeason()}
                >
                  {page.downloadingBest ? 'Finding Best…' : 'Download Best'}
                </button>
                <button
                  class="rounded-xl px-4 py-2 bg-onyx-raised hover:bg-slate-700 border border-onyx-border text-slate-200 text-xs font-semibold transition-colors cursor-pointer"
                  type="button"
                  data-testid="season-pack-releases"
                  onclick={() => void openSeasonPacks()}
                >
                  Season Pack Releases
                </button>
              </div>
            </header>

            <!-- Full-height episode list -->
            <div class="divide-y divide-onyx-border/60" data-testid="episode-list" data-season={activeSeason}>
              {#each currentEpisodes as episode (episode.episode_number)}
                <div
                  class="px-5 py-3.5 flex items-center justify-between gap-4 hover:bg-white/[0.025] transition-colors"
                  data-testid="episode-row"
                  data-season={activeSeason}
                  data-episode={episode.episode_number}
                >
                  <div class="flex items-center gap-3.5 min-w-0 flex-1">
                    <span class="w-10 text-center rounded-md bg-onyx-obsidian border border-onyx-border/80 py-1 font-mono text-xs font-bold text-indigo-400 shrink-0">
                      E{String(episode.episode_number).padStart(2, '0')}
                    </span>
                    <div class="min-w-0 flex-1">
                      <div class="flex items-center gap-2">
                        <span class="text-sm font-medium text-slate-100 truncate">
                          {episode.name || `Episode ${episode.episode_number}`}
                        </span>
                        {#if episode.available}
                          <span
                            class="shrink-0 inline-flex items-center rounded-md bg-emerald-500/15 border border-emerald-500/35 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-300"
                            data-testid="episode-badge"
                            data-status="available"
                          >
                            Available
                          </span>
                        {/if}
                      </div>
                      {#if episode.air_date}
                        <p class="text-[11px] text-slate-500 font-mono mt-0.5">{episode.air_date}</p>
                      {/if}
                    </div>
                  </div>

                  <button
                    class="shrink-0 rounded-lg px-3.5 py-1.5 bg-indigo-500/15 hover:bg-indigo-600 border border-indigo-500/30 hover:border-indigo-500 text-indigo-300 hover:text-white text-xs font-semibold transition-colors cursor-pointer"
                    type="button"
                    data-testid="episode-releases"
                    data-episode={episode.episode_number}
                    onclick={episode.onReleases}
                  >
                    Releases
                  </button>
                </div>
              {/each}
            </div>
          </section>
        {/if}
      </div>
    {/if}

    {#if drawerState?.open}
      <ReleaseDrawer items={drawerRows} scope={'tv'} title={details?.title ?? 'Releases'} />
    {/if}

    {#if details.similar.length > 0}
      <MediaRail title="More Like This" items={details.similar} kind={'tv'} />
    {/if}
  {:else if page.error}
    <div
      class="rounded-2xl p-6 bg-onyx-surface border border-amber-700/40 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4"
      data-testid="tv-detail-error"
      role="status"
      aria-live="polite"
    >
      <div class="space-y-1">
        <p class="text-sm font-semibold text-amber-300">Could not load TV show details</p>
        <p class="text-xs text-slate-400" data-testid="tv-detail-error-message">{page.error}</p>
      </div>
      <button
        class="rounded-xl px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold cursor-pointer"
        type="button"
        data-testid="tv-detail-retry"
        onclick={ensureLoaded}
      >
        Retry now
      </button>
    </div>
  {:else}
    <div class="space-y-6" data-testid="tv-detail-loading" role="status" aria-busy="true">
      <span class="sr-only">Loading show details…</span>
      <div class="h-72 sm:h-80 rounded-2xl border border-onyx-border/60 skeleton-pulse"></div>
      <div class="h-64 rounded-2xl border border-onyx-border/60 skeleton-pulse"></div>
    </div>
  {/if}
</div>
