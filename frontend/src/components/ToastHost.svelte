<!-- Toast notification stack with clickable actions and auto-dismiss. -->
<script lang="ts">
  import { dismissToast, dismissToastsAfter, toasts } from '../lib/stores/ui.svelte';
  import { navigate } from '../lib/router.svelte';

  const TOAST_LIFE_MS = 7000;

  $effect(() => {
    if (toasts().length > 0) dismissToastsAfter(TOAST_LIFE_MS);
  });

  function cardTone(kind: 'info' | 'success' | 'error'): string {
    if (kind === 'success') return 'border-emerald-500/40 bg-emerald-950/90 text-emerald-100';
    if (kind === 'error') return 'border-rose-500/45 bg-rose-950/90 text-rose-100';
    return 'border-indigo-500/40 bg-onyx-surface/95 text-slate-100';
  }

  function dotTone(kind: 'info' | 'success' | 'error'): string {
    if (kind === 'success') return 'bg-emerald-400';
    if (kind === 'error') return 'bg-rose-400';
    return 'bg-indigo-400';
  }
</script>

<div
  class="pointer-events-none fixed bottom-20 lg:bottom-6 right-4 sm:right-6 z-50 flex flex-col items-end gap-2.5 max-w-sm w-[calc(100%-2rem)]"
  aria-live="polite"
  aria-atomic="false"
  data-testid="toast-host"
>
  {#each toasts() as toast, index}
    <div
      class="pointer-events-auto modal-pop-in w-full flex items-center justify-between gap-3 rounded-xl px-4 py-3 border backdrop-blur-md shadow-xl shadow-black/50 text-xs sm:text-sm {cardTone(toast.kind)}"
      data-testid={`toast-${index}`}
      role="status"
    >
      <div class="flex items-center gap-2.5 min-w-0">
        <span class="w-2 h-2 rounded-full shrink-0 {dotTone(toast.kind)}" aria-hidden="true"></span>
        <span class="leading-snug break-words">{toast.message}</span>
      </div>
      <div class="flex items-center gap-2 shrink-0">
        {#if toast.actionPath}
          <button
            class="rounded-lg px-2.5 py-1 text-xs font-semibold bg-white/10 hover:bg-white/20 text-white transition-colors whitespace-nowrap cursor-pointer"
            type="button"
            data-testid={`toast-action-${index}`}
            title={toast.actionLabel}
            onclick={() => {
              dismissToast(index);
              navigate(toast.actionPath ?? '/queue');
            }}
          >
            {toast.actionLabel}
          </button>
        {/if}
        <button
          type="button"
          aria-label="Dismiss notification"
          class="text-current/70 hover:text-white text-base leading-none px-1 cursor-pointer"
          onclick={() => dismissToast(index)}
        >
          &times;
        </button>
      </div>
    </div>
  {/each}
</div>
