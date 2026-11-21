<!-- Dedicated view components (all ten registered views) rather than one
     toggle: each page consumes only its own payload, so memory is bounded per
     view instead of every view rendering from one store. -->
<script lang="ts">
  import { route } from '../lib/router.svelte';
  import DiscoverPage from './DiscoverPage.svelte';
  import BrowsePage from './BrowsePage.svelte';
  import SearchPage from './SearchPage.svelte';
  import MovieDetailPage from './MovieDetailPage.svelte';
  import TvDetailPage from './TvDetailPage.svelte';
  import LibraryPage from './LibraryPage.svelte';
  import MonitoredPage from './MonitoredPage.svelte';
  import QueuePage from './QueuePage.svelte';
  import SettingsPage from './SettingsPage.svelte';

  const view = $derived(route()?.view);
</script>

{#if view === 'search'}
  <SearchPage />
{:else if view === 'movie'}
  <MovieDetailPage />
{:else if view === 'tvshow'}
  <TvDetailPage />
{:else if view === 'library'}
  <LibraryPage />
{:else if view === 'queue'}
  <QueuePage />
{:else if view === 'monitored'}
  <MonitoredPage />
{:else if view === 'settings'}
  <SettingsPage />
{:else if view === 'movies' || view === 'tv'}
  <BrowsePage />
{:else}
  <DiscoverPage />
{/if}
