<!-- Ctrl+K command palette: instant local Library + recent searches + quick
     route jump with zero network calls while typing; Enter navigates to
     /search?q=... for unified parallel Movie + TV results. -->
<script lang="ts">
  import { completion, observeKeyboard, submitPaletteQuery } from '../lib/palette';
  import { navigate } from '../lib/router.svelte';
  import { palette, setPalette } from '../lib/stores/ui.svelte';

  observeKeyboard();

  let inputEl = $state<HTMLInputElement | null>(null);
  let activeIndex = $state(0);

  const paletteState = $derived(palette());
  const opened = $derived(paletteState.open);
  const query = $derived(paletteState.query);
  const matches = $derived(completion(query));

  $effect(() => {
    if (opened && inputEl) {
      inputEl.focus();
      activeIndex = 0;
    }
  });

  function close(): void {
    setPalette(false, '');
  }

  function handleInput(event: Event): void {
    const value = (event.currentTarget as HTMLInputElement).value;
    setPalette(true, value);
    activeIndex = 0;
  }

  function handleKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (matches.length > 0) activeIndex = (activeIndex + 1) % matches.length;
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (matches.length > 0) activeIndex = (activeIndex - 1 + matches.length) % matches.length;
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      if (query.trim()) {
        submitPaletteQuery(query);
      } else if (matches[activeIndex]?.path) {
        const dest = matches[activeIndex].path;
        close();
        if (dest) navigate(dest);
      }
    }
  }

  function openMatch(path: string | undefined): void {
    close();
    if (path) navigate(path);
  }
</script>

{#if opened}
  <div
    class="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-start justify-center pt-[12vh] px-4 contain-scroll"
    data-testid="palette-backdrop"
    onclick={(event) => {
      if (event.target === event.currentTarget) close();
    }}
    role="presentation"
  >
    <div
      class="modal-pop-in w-full max-w-xl rounded-2xl bg-onyx-surface border border-onyx-border shadow-2xl shadow-black/70 overflow-hidden contain-scroll"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      data-testid="command-palette"
    >
      <!-- Search input bar -->
      <div class="flex items-center gap-3 px-4 py-3.5 border-b border-onyx-border/80">
        <svg aria-hidden="true" class="w-5 h-5 text-indigo-400 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-4.35-4.35M17 11a6 6 0 11-12 0 6 6 0 0112 0z" />
        </svg>
        <input
          bind:this={inputEl}
          type="search"
          value={query}
          oninput={handleInput}
          onkeydown={handleKeydown}
          placeholder="Search movies, TV shows, or jump to your library…"
          aria-label="Global search"
          data-testid="palette-input"
          class="flex-1 bg-transparent text-sm sm:text-base text-white placeholder-slate-500 focus:outline-none"
        />
        <span class="sr-only" data-testid="palette-query">{query}</span>
        {#if query}
          <button
            type="button"
            class="text-xs text-slate-400 hover:text-white px-1.5 py-0.5 rounded cursor-pointer"
            onclick={() => setPalette(true, '')}
            aria-label="Clear search"
          >
            Clear
          </button>
        {/if}
        <kbd class="hidden sm:inline-block rounded-md bg-onyx-obsidian border border-onyx-border px-1.5 py-0.5 text-[10px] font-mono text-slate-400">
          Esc
        </kbd>
      </div>

      <!-- Primary Enter-to-search action when query is non-empty -->
      {#if query.trim()}
        <div class="p-2 border-b border-onyx-border/60 bg-indigo-500/[0.06]">
          <button
            type="button"
            data-testid="palette-search"
            class="w-full flex items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium text-indigo-200 hover:bg-indigo-500/20 transition-colors cursor-pointer"
            onclick={() => submitPaletteQuery(query)}
          >
            <span class="flex items-center gap-2.5 truncate">
              <span class="inline-flex items-center justify-center w-6 h-6 rounded-lg bg-indigo-600 text-white text-xs font-bold shrink-0">↵</span>
              <span class="truncate">Search IMDb &amp; TVMaze for “<strong class="text-white">{query.trim()}</strong>”</span>
            </span>
            <span class="text-[11px] text-indigo-300/80 shrink-0">Enter</span>
          </button>
        </div>
      {/if}

      <!-- Local instant matches (Library + Recent + Routes) -->
      <div class="max-h-80 overflow-y-auto p-2">
        <div class="flex items-center justify-between px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
          <span>Quick matches</span>
          <span data-testid="palette-local">Local library &amp; shortcuts</span>
        </div>

        {#if matches.length > 0}
          <ul class="space-y-0.5" data-testid="palette-matches">
            {#each matches as match, index}
              <li data-testid={`palette-match-${index}`}>
                <button
                  type="button"
                  title={match.path}
                  class="w-full flex items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-sm transition-colors cursor-pointer {index === activeIndex
                    ? 'bg-onyx-raised text-white'
                    : 'text-slate-300 hover:bg-white/[0.04] hover:text-white'}"
                  onmouseenter={() => (activeIndex = index)}
                  onclick={() => openMatch(match.path)}
                >
                  <span class="flex items-center gap-2.5 min-w-0">
                    <span
                      class="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide shrink-0 {match.category === 'library'
                        ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                        : match.category === 'recent'
                          ? 'bg-slate-800 text-slate-400 border border-slate-700'
                          : 'bg-indigo-500/15 text-indigo-300 border border-indigo-500/30'}"
                    >
                      {match.category === 'library' ? 'Lib' : match.category === 'recent' ? 'Recent' : 'Go'}
                    </span>
                    <span class="truncate font-medium">{match.label}</span>
                  </span>
                  {#if match.sublabel}
                    <span class="text-[11px] text-slate-500 font-mono shrink-0">{match.sublabel}</span>
                  {/if}
                </button>
              </li>
            {/each}
          </ul>
        {:else}
          <p class="px-3 py-6 text-center text-xs text-slate-500" data-testid="palette-matches">
            No local matches. Press <kbd class="px-1.5 py-0.5 rounded bg-onyx-obsidian border border-onyx-border text-slate-300 font-mono">Enter</kbd> to search movies &amp; TV shows.
          </p>
        {/if}
      </div>

      {#if !query.trim()}
        <div class="px-4 py-2.5 border-t border-onyx-border/70 bg-onyx-obsidian/50 flex items-center justify-between text-[11px] text-slate-500">
          <span>Type a title and hit Enter to search everywhere</span>
          <button
            type="button"
            data-testid="palette-search"
            class="text-indigo-400 hover:text-indigo-300 font-medium cursor-pointer"
            onclick={() => submitPaletteQuery(query)}
          >
            Search
          </button>
        </div>
      {/if}
    </div>
  </div>
{:else}
  <div class="hidden" data-testid="palette-closed"></div>
{/if}
