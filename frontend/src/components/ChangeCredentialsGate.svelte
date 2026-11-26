<!-- Forced credential change: shown full viewport after the first (default)
     login. No complexity rules, not dismissible — submitting is the only way
     to the dashboard. -->
<script lang="ts">
  import { navigate } from '../lib/router.svelte';
  import { changeCredentials } from '../lib/stores/auth.svelte';

  let username = '';
  let password = '';
  let error = '';
  let busy = false;

  async function submit(): Promise<void> {
    if (busy) return;
    if (!username.trim() || !password) {
      error = 'Username and password are required.';
      return;
    }
    busy = true;
    error = '';
    const ok = await changeCredentials(username.trim(), password);
    busy = false;
    if (!ok) {
      error = 'Failed to update credentials.';
      return;
    }
    navigate('/');
  }
</script>

<div class="min-h-screen w-full bg-onyx-obsidian text-onyx-text flex items-center justify-center px-4">
  <form
    class="w-full max-w-sm rounded-2xl border border-onyx-border/80 bg-onyx-obsidian/70 p-6 space-y-4"
    onsubmit={(e) => {
      e.preventDefault();
      void submit();
    }}
    data-testid="credentials-gate"
  >
    <div class="space-y-1">
      <div class="text-lg font-bold tracking-tight">Change your credentials</div>
      <p class="text-xs text-onyx-muted">
        You signed in with the default account. Choose a new username and password to continue.
      </p>
    </div>

    <label class="block space-y-1.5">
      <span class="text-xs font-semibold text-slate-300">New username</span>
      <input
        type="text"
        bind:value={username}
        autocomplete="username"
        data-testid="gate-username"
        class="w-full rounded-xl px-3.5 py-2.5 bg-onyx-obsidian border border-onyx-border text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
      />
    </label>

    <label class="block space-y-1.5">
      <span class="text-xs font-semibold text-slate-300">New password</span>
      <input
        type="password"
        bind:value={password}
        autocomplete="new-password"
        data-testid="gate-password"
        class="w-full rounded-xl px-3.5 py-2.5 bg-onyx-obsidian border border-onyx-border text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
      />
    </label>

    {#if error}
      <p class="text-xs text-red-400" data-testid="gate-error" role="alert">{error}</p>
    {/if}

    <button
      type="submit"
      disabled={busy}
      data-testid="gate-submit"
      class="w-full rounded-xl px-3.5 py-2.5 bg-onyx-indigo hover:opacity-90 text-sm font-semibold text-white transition-opacity cursor-pointer disabled:opacity-50"
    >
      {busy ? 'Saving…' : 'Save and continue'}
    </button>
  </form>
</div>
