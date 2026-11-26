<!-- Login screen: username + password with a generic 401 error. Shown full
     viewport while unauthenticated (no sidebar/top bar). -->
<script lang="ts">
  import { navigate } from '../lib/router.svelte';
  import { login, authMustChange } from '../lib/stores/auth.svelte';

  let username = '';
  let password = '';
  let error = '';
  let busy = false;

  async function submit(): Promise<void> {
    if (busy) return;
    busy = true;
    error = '';
    const ok = await login(username, password);
    busy = false;
    if (!ok) {
      error = 'Invalid username or password.';
      return;
    }
    // Authenticated: the gate (must-change) or the shell takes over via
    // AppShell's reactive state; land on the home view.
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
    data-testid="login-form"
  >
    <div class="space-y-1">
      <div class="text-2xl font-bold tracking-tight">Onyx</div>
      <p class="text-xs text-onyx-muted">Sign in to your media dashboard.</p>
    </div>

    <label class="block space-y-1.5">
      <span class="text-xs font-semibold text-slate-300">Username</span>
      <input
        type="text"
        bind:value={username}
        autocomplete="username"
        data-testid="login-username"
        class="w-full rounded-xl px-3.5 py-2.5 bg-onyx-obsidian border border-onyx-border text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
      />
    </label>

    <label class="block space-y-1.5">
      <span class="text-xs font-semibold text-slate-300">Password</span>
      <input
        type="password"
        bind:value={password}
        autocomplete="current-password"
        data-testid="login-password"
        class="w-full rounded-xl px-3.5 py-2.5 bg-onyx-obsidian border border-onyx-border text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
      />
    </label>

    {#if error}
      <p class="text-xs text-red-400" data-testid="login-error" role="alert">{error}</p>
    {/if}

    <button
      type="submit"
      disabled={busy}
      data-testid="login-submit"
      class="w-full rounded-xl px-3.5 py-2.5 bg-onyx-indigo hover:opacity-90 text-sm font-semibold text-white transition-opacity cursor-pointer disabled:opacity-50"
    >
      {busy ? 'Signing in…' : 'Sign in'}
    </button>
  </form>
</div>
