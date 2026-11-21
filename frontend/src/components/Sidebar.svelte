<!-- Collapsible desktop sidebar: Browse / My Media / System sections, queue
     count badge, and persistent live transfer footer. -->
<script lang="ts">
  import NavIcon from './NavIcon.svelte';
  import { currentPath, navigate } from '../lib/router.svelte';
  import { NAV_SECTIONS } from '../lib/nav';
  import { formatSpeed } from '../lib/api';
  import { queueCount, totalDownloadRate, totalUploadRate, wsConnected } from '../lib/stores/queue.svelte';
  import { sidebarCollapsed, setSidebarCollapsed } from '../lib/stores/ui.svelte';

  const collapsed = $derived(sidebarCollapsed());
  const activePath = $derived(currentPath());
  const activeCount = $derived(queueCount());
  const downRate = $derived(totalDownloadRate());
  const upRate = $derived(totalUploadRate());
  const live = $derived(wsConnected());

  function isActive(itemPath: string): boolean {
    if (itemPath === '/') return activePath === '/';
    return activePath === itemPath;
  }
</script>

<aside
  class="hidden lg:flex flex-col shrink-0 sticky top-0 h-screen bg-onyx-surface/95 border-r border-onyx-border/80 transition-[width] duration-200 {collapsed ? 'w-[74px]' : 'w-60'}"
  aria-label="Primary navigation"
  data-testid="sidebar"
>
  <!-- Brand + collapse button -->
  <div class="h-16 px-3.5 flex items-center {collapsed ? 'justify-center' : 'justify-between'} border-b border-onyx-border/70">
    {#if !collapsed}
      <a
        href="/"
        class="inline-flex items-center select-none group"
        onclick={(event) => {
          event.preventDefault();
          navigate('/');
        }}
      >
        <span class="font-black text-2xl leading-none tracking-[0.3em] bg-gradient-to-r from-white via-slate-200 to-indigo-400 bg-clip-text text-transparent">
          ONYX
        </span>
      </a>
    {/if}
    <button
      class="w-8 h-8 rounded-lg border border-onyx-border/70 bg-onyx-obsidian/60 text-onyx-muted hover:text-white hover:border-slate-600 flex items-center justify-center transition-colors cursor-pointer"
      type="button"
      data-testid="sidebar-collapse-toggle"
      aria-label="Toggle sidebar width"
      title="Collapse the sidebar to an icon rail; the preference is remembered across reloads"
      onclick={() => setSidebarCollapsed(!sidebarCollapsed())}
    >
      <svg
        aria-hidden="true"
        class="w-4 h-4 transition-transform duration-200 {collapsed ? 'rotate-180' : ''}"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        viewBox="0 0 24 24"
      >
        <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
      </svg>
    </button>
  </div>

  <!-- Navigation sections -->
  <nav class="flex-1 overflow-y-auto px-2.5 py-4 space-y-5" aria-label="Sidebar sections">
    {#each NAV_SECTIONS as section (section.key)}
      <section class="space-y-1" data-section={section.key} aria-label={section.label}>
        {#if !collapsed}
          <p class="px-2.5 pb-1 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
            {section.label}
          </p>
        {:else if section.key !== 'browse'}
          <div class="mx-2 my-2 h-px bg-onyx-border/60" aria-hidden="true"></div>
        {/if}

        {#each section.items as item (item.path)}
          {@const active = isActive(item.path)}
          <a
            class="relative group flex items-center {collapsed ? 'justify-center px-0 py-2.5' : 'justify-between px-3 py-2'} rounded-xl text-sm font-medium transition-colors border {active
              ? 'bg-indigo-500/15 text-white border-indigo-500/35 shadow-sm shadow-indigo-950/40'
              : 'border-transparent text-slate-400 hover:text-slate-100 hover:bg-white/[0.04]'}"
            href={item.path}
            data-nav={item.path}
            data-testid={`nav-${item.path === '/' ? 'discover' : item.path.slice(1)}`}
            aria-current={active ? 'page' : undefined}
            title={item.label}
            onclick={(event) => {
              event.preventDefault();
              navigate(item.path);
            }}
          >
            <span class="flex items-center gap-3 min-w-0">
              <NavIcon
                icon={item.icon}
                className="w-[18px] h-[18px] shrink-0 {active ? 'text-indigo-400' : 'text-slate-400 group-hover:text-slate-200'}"
              />
              {#if collapsed}
                <span class="sr-only">{item.label}</span>
              {:else}
                <span class="truncate">{item.label}</span>
              {/if}
            </span>

            {#if item.path === '/queue'}
              <span
                class="{collapsed
                  ? 'absolute top-1 right-1.5 min-w-[16px] h-4 px-1 text-[10px] leading-4'
                  : 'px-2 py-0.5 text-[11px]'} inline-flex items-center justify-center rounded-full font-semibold tabular-nums {activeCount > 0
                  ? 'bg-indigo-500/25 text-indigo-300 border border-indigo-400/30'
                  : 'bg-onyx-raised text-slate-400'}"
                data-testid="queue-count"
              >
                {activeCount}
              </span>
            {/if}
          </a>
        {/each}
      </section>
    {/each}
  </nav>

  <!-- Live Transfer Footer -->
  <div
    class="mt-auto border-t border-onyx-border/80 bg-onyx-obsidian/60 px-3 py-3"
    data-testid="transfer-footer"
  >
    {#if collapsed}
      <div class="flex flex-col items-center gap-1.5">
        <span
          class="w-2.5 h-2.5 rounded-full {live ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.65)]' : 'bg-amber-400'}"
          data-testid="connection-dot"
          data-connected={live}
          title={live ? 'Live /ws/queue connected' : 'Reconnecting to /ws/queue'}
        ></span>
        <span class="text-[10px] font-mono text-slate-400 tabular-nums" data-testid="transfer-download">
          ↓ {formatSpeed(downRate)}
        </span>
        <span class="sr-only" data-testid="transfer-upload">↑ {formatSpeed(upRate)}</span>
      </div>
    {:else}
      <div class="flex items-center justify-between mb-2">
        <span class="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">Transfers</span>
        <span class="inline-flex items-center gap-1.5 text-[11px] font-medium {live ? 'text-emerald-400' : 'text-amber-400'}">
          <span
            class="w-2 h-2 rounded-full {live ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.65)]' : 'bg-amber-400'}"
            data-testid="connection-dot"
            data-connected={live}
            title={live ? 'Live /ws/queue connected' : 'Reconnecting to /ws/queue'}
          ></span>
          {live ? 'Live' : 'Syncing'}
        </span>
      </div>
      <div class="grid grid-cols-2 gap-1.5 text-[11px] font-mono tabular-nums">
        <div class="rounded-lg bg-onyx-surface border border-onyx-border/60 px-2 py-1.5 flex items-center gap-1.5 text-slate-200 truncate">
          <span class="text-indigo-400 font-bold" aria-hidden="true">↓</span>
          <span class="truncate" data-testid="transfer-download">{formatSpeed(downRate)}</span>
        </div>
        <div class="rounded-lg bg-onyx-surface border border-onyx-border/60 px-2 py-1.5 flex items-center gap-1.5 text-slate-300 truncate">
          <span class="text-emerald-400 font-bold" aria-hidden="true">↑</span>
          <span class="truncate" data-testid="transfer-upload">{formatSpeed(upRate)}</span>
        </div>
      </div>
    {/if}
  </div>
</aside>
