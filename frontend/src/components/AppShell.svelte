<!-- App shell: collapsible sidebar, persistent top bar, offline outage
     banner, routed main viewport, mobile nav, command palette, confirmation
     dialog, and toast host. -->
<script lang="ts">
  import ConfirmDialog from './ConfirmDialog.svelte';
  import CommandPalette from './CommandPalette.svelte';
  import MobileNav from './MobileNav.svelte';
  import Sidebar from './Sidebar.svelte';
  import ToastHost from './ToastHost.svelte';
  import TopBar from './TopBar.svelte';
  import ViewSlot from './ViewSlot.svelte';
  import {
    backendDown,
    closeSocket,
    openSocket,
    retryDelayMs,
    retryNow,
  } from '../lib/stores/queue.svelte';
  import { refreshIfStale } from '../lib/stores/library.svelte';
  import { observeHistory, syncLocation } from '../lib/router.svelte';
  import {
    authMustChange,
    authStatus,
    fetchStatus,
  } from '../lib/stores/auth.svelte';
  import LoginPage from './LoginPage.svelte';
  import ChangeCredentialsGate from './ChangeCredentialsGate.svelte';

  let initialized = false;
  $effect(() => {
    observeHistory();
    if (initialized) return;
    initialized = true;
    syncLocation();
    // Resolve the session before any view loads, and pre-warm the local
    // library cache for instant Ctrl+K matching.
    void fetchStatus();
    void refreshIfStale(60_000).catch(() => void 0);
  });

  // The live /ws/queue feed only opens once the session is valid and the
  // forced credential change has been made; the cleanup tears the socket
  // down (and its pending retry) when the state leaves that branch.
  $effect(() => {
    const status = authStatus();
    const mustChange = authMustChange();
    const isJsdom = typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent);
    if (status !== 'authenticated' || mustChange) return;
    if (isJsdom || typeof globalThis.WebSocket !== 'function') return;
    openSocket();
    return () => closeSocket();
  });
</script>

{#if authStatus() === 'loading'}
  <div class="min-h-screen w-full bg-onyx-obsidian text-onyx-text flex items-center justify-center" data-testid="auth-loading">
    <p class="text-sm text-onyx-muted">Loading session…</p>
  </div>
{:else if authStatus() === 'unauthenticated'}
  <LoginPage />
{:else if authMustChange()}
  <ChangeCredentialsGate />
{:else}
<div class="min-h-screen w-full bg-onyx-obsidian text-onyx-text flex">
  <Sidebar />

  <div class="flex-1 min-w-0 flex flex-col min-h-screen">
    <TopBar />

    {#if backendDown()}
      <div
        class="mx-4 sm:mx-6 lg:mx-8 mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl px-4 py-3 bg-amber-950/60 border border-amber-700/60 text-amber-200 text-xs sm:text-sm"
        data-testid="backend-banner"
        role="alert"
        aria-live="polite"
      >
        <div class="flex items-center gap-2.5">
          <span class="w-2 h-2 rounded-full bg-amber-400 shrink-0" aria-hidden="true"></span>
          <span>Can’t reach the Onyx backend or Transmission. Queue data may be stale.</span>
        </div>
        <div class="flex items-center gap-3 text-xs text-amber-300/90" data-testid="retry-countdown">
          <span>Retrying in {Math.ceil(retryDelayMs() / 1000)}s</span>
          <button
            class="rounded-lg px-3 py-1 bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-100 font-semibold transition-colors cursor-pointer"
            type="button"
            onclick={retryNow}
          >
            Retry Now
          </button>
        </div>
      </div>
    {/if}

    <main
      class="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 pb-24 lg:pb-10"
      data-testid="drawer-host"
    >
      <ViewSlot />
    </main>
  </div>

  <MobileNav />
  <CommandPalette />
  <ConfirmDialog />
  <ToastHost />
</div>
{/if}
