<!-- Mobile bottom nav bar: replaces the desktop sidebar below lg. -->
<script lang="ts">
  import NavIcon from './NavIcon.svelte';
  import { currentPath, navigate } from '../lib/router.svelte';
  import { NAV_SECTIONS } from '../lib/nav';
  import { queueCount } from '../lib/stores/queue.svelte';

  const items = NAV_SECTIONS.flatMap((section) => section.items);
  const activePath = $derived(currentPath());
  const activeCount = $derived(queueCount());
</script>

<nav
  class="lg:hidden fixed bottom-0 inset-x-0 z-40 flex items-center justify-around px-1 py-1.5 bg-onyx-surface/95 backdrop-blur-md border-t border-onyx-border shadow-2xl"
  aria-label="Mobile navigation"
  data-testid="mobile-nav"
>
  {#each items as item (item.path)}
    {@const active = item.path === activePath}
    <button
      class="relative flex flex-col items-center justify-center gap-0.5 flex-1 min-w-0 py-1 rounded-lg transition-colors cursor-pointer {active
        ? 'text-indigo-400'
        : 'text-slate-400 hover:text-slate-200'}"
      type="button"
      data-nav={item.path}
      data-testid={`mobile-nav-${item.path === '/' ? 'discover' : item.path.slice(1)}`}
      aria-current={active ? 'page' : undefined}
      title={item.label}
      onclick={() => navigate(item.path)}
    >
      <NavIcon icon={item.icon} className="w-5 h-5" />
      <span class="text-[10px] font-medium truncate max-w-full px-0.5">{item.shortLabel}</span>
      {#if item.path === '/queue' && activeCount > 0}
        <span class="absolute top-0.5 right-1/2 translate-x-3.5 min-w-[15px] h-[15px] px-1 rounded-full bg-indigo-600 text-white text-[9px] font-bold leading-[15px] text-center">
          {activeCount}
        </span>
      {/if}
    </button>
  {/each}
</nav>
