<!-- Global confirmation dialog: gates destructive removals and duplicate-library
     HTTP 409 downloads behind explicit user confirmation. -->
<script lang="ts">
  import { answerConfirmation, confirmation } from '../lib/stores/ui.svelte';

  const pending = $derived(confirmation());
  const isDuplicate = $derived(pending?.kind === 'duplicate');
  const acceptText = $derived(
    pending?.confirmLabel ?? (isDuplicate ? 'Download again' : 'Confirm'),
  );

  $effect(() => {
    if (!pending) return;
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') {
        event.preventDefault();
        answerConfirmation(false);
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  });
</script>

{#if pending}
  <div
    class="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm contain-scroll"
    data-testid="confirm-overlay"
    role="presentation"
    onclick={(event) => {
      if (event.target === event.currentTarget) answerConfirmation(false);
    }}
  >
    <div
      class="modal-pop-in max-w-md w-full flex flex-col gap-4 rounded-2xl p-6 bg-onyx-surface border border-onyx-border shadow-2xl shadow-black/80"
      data-testid="confirm-dialog"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
      tabindex="-1"
    >
      <div class="flex items-start gap-3.5">
        <div
          class="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 border {isDuplicate
            ? 'bg-amber-500/15 border-amber-500/35 text-amber-300'
            : 'bg-rose-500/15 border-rose-500/35 text-rose-400'}"
          aria-hidden="true"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          </svg>
        </div>
        <div class="min-w-0">
          <h2 id="confirm-title" class="text-base font-bold text-white">
            {pending.title}
          </h2>
          <p class="mt-1 text-sm text-slate-300 leading-relaxed" data-testid="confirm-message">
            {pending.message}
          </p>
        </div>
      </div>

      {#if isDuplicate}
        <p
          class="rounded-xl px-3.5 py-2.5 bg-amber-950/40 border border-amber-700/40 text-xs text-amber-200"
          data-testid="confirm-duplicate"
        >
          Already in your library — downloading again may create a duplicate or overwrite files.
        </p>
      {:else}
        <p
          class="rounded-xl px-3.5 py-2.5 bg-rose-950/40 border border-rose-800/50 text-xs text-rose-300"
          data-testid="confirm-danger"
        >
          This action removes data and cannot be undone.
        </p>
      {/if}

      <div class="flex items-center justify-end gap-2.5 pt-1">
        <button
          class="rounded-xl px-4 py-2 text-xs sm:text-sm font-semibold bg-onyx-raised hover:bg-slate-700 text-slate-200 border border-onyx-border transition-colors cursor-pointer"
          type="button"
          data-testid="confirm-cancel"
          onclick={() => answerConfirmation(false)}
        >
          Cancel
        </button>
        <button
          class="rounded-xl px-4 py-2 text-xs sm:text-sm font-semibold text-white transition-colors cursor-pointer {isDuplicate
            ? 'bg-indigo-600 hover:bg-indigo-500 shadow-md shadow-indigo-950/60'
            : 'bg-rose-600 hover:bg-rose-500 shadow-md shadow-rose-950/60'}"
          type="button"
          data-testid="confirm-accept"
          onclick={() => answerConfirmation(true)}
        >
          {acceptText}
        </button>
      </div>
    </div>
  </div>
{:else}
  <div class="hidden" data-testid="confirm-closed"></div>
{/if}
