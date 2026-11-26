// Web-auth state: session status, login, forced credential change, logout.
// The SPA fetches /api/auth/status on mount; AppShell renders the login page,
// the credential-change gate, or the normal shell from this state.
import { request } from '../api';

export type AuthStatus = 'loading' | 'unauthenticated' | 'authenticated';

interface AuthState {
  status: AuthStatus;
  username: string;
  mustChange: boolean;
}

const auth = $state<AuthState>({ status: 'loading', username: '', mustChange: false });

// Test seam: every (re)application of the auth state bumps a version, and
// authSettled() resolves on the next bump — tests await the real signal
// instead of a guessed delay.
let stateVersion = 0;
const stateWaits: Array<{ after: number; resolve: () => void }> = [];

function bumpState(): void {
  stateVersion += 1;
  const pending: typeof stateWaits = [];
  for (const wait of stateWaits) {
    if (wait.after < stateVersion) wait.resolve();
    else pending.push(wait);
  }
  stateWaits.length = 0;
  stateWaits.push(...pending);
}

/** Resolves once the auth state has been applied at least once since the call. */
export function authSettled(): Promise<void> {
  const { promise, resolve } = Promise.withResolvers<void>();
  stateWaits.push({ after: stateVersion, resolve });
  return promise;
}

/** Test seam: return the store to its initial loading state. */
export function resetAuth(): void {
  auth.status = 'loading';
  auth.username = '';
  auth.mustChange = false;
  bumpState();
}

export function authStatus(): AuthStatus {
  return auth.status;
}

export function authUsername(): string {
  return auth.username;
}

export function authMustChange(): boolean {
  return auth.mustChange;
}

/** Flip to unauthenticated (used by the 401 handler in the API client). */
export function markUnauthenticated(): void {
  auth.status = 'unauthenticated';
  auth.username = '';
  auth.mustChange = false;
  bumpState();
}

function applyStatus(data: {
  authenticated: boolean;
  username?: string | null;
  must_change_credentials: boolean;
}): void {
  if (data.authenticated) {
    auth.status = 'authenticated';
    auth.username = data.username ?? '';
    auth.mustChange = data.must_change_credentials;
  } else {
    markUnauthenticated();
  }
  bumpState();
}

/** Fetch the session status (called on mount and after auth transitions). */
export async function fetchStatus(): Promise<void> {
  try {
    const data = (await request('GET', '/api/auth/status')) as {
      authenticated: boolean;
      username?: string | null;
      must_change_credentials: boolean;
    };
    applyStatus(data);
  } catch {
    markUnauthenticated();
  }
}

/** Login; returns false on a rejected credential pair (401). */
export async function login(username: string, password: string): Promise<boolean> {
  try {
    const data = (await request('POST', '/api/auth/login', {
      username,
      password,
    })) as { authenticated: boolean; username?: string | null; must_change_credentials: boolean };
    applyStatus(data);
    return true;
  } catch {
    bumpState();
    return false;
  }
}

/** Submit the forced credential change; returns false on failure. */
export async function changeCredentials(username: string, password: string): Promise<boolean> {
  try {
    const data = (await request('POST', '/api/auth/change-credentials', {
      username,
      password,
    })) as { authenticated: boolean; username?: string | null; must_change_credentials: boolean };
    applyStatus(data);
    return true;
  } catch {
    bumpState();
    return false;
  }
}

/** Log out and end the session. */
export async function logout(): Promise<void> {
  try {
    await request('POST', '/api/auth/logout');
  } catch {
    // The session is best-effort server-side; always land on the login page.
  }
  markUnauthenticated();
}
