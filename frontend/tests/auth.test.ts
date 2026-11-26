// Auth flow: store state (status/login), the login page and credential-change
// gate rendering, the gated /ws/queue socket, and the 401 -> /login redirect.
import { afterEach, beforeEach, expect, test } from 'vitest';
import { render } from '@testing-library/svelte';
import AppShell from '../src/components/AppShell.svelte';
import { api } from '../src/lib/api';
import { currentPath } from '../src/lib/router.svelte';
import {
  authMustChange,
  authSettled,
  authStatus,
  changeCredentials,
  fetchStatus,
  login,
  resetAuth,
} from '../src/lib/stores/auth.svelte';
import type { FetchResponse } from './auth';

declare const globalThis: {
  fetch: (path: string, options?: unknown) => FetchResponse;
  WebSocket: unknown;
};

const realFetch = globalThis.fetch;
const realWebSocket = globalThis.WebSocket;

// The auth status fetch settles the shell re-render; await the real state
// signal, not a guessed delay.
const shellReady = () => authSettled();

const noMock: FetchResponse = { ok: false, status: 503, statusText: 'no mock', text: async () => '' };

const statusBody = (authenticated: boolean, mustChange: boolean): FetchResponse => ({
  ok: true,
  status: 200,
  statusText: 'OK',
  text: async () =>
    JSON.stringify({
      authenticated,
      username: authenticated ? 'admin' : null,
      must_change_credentials: mustChange,
    }),
});

interface RecordedCall {
  path: string;
  body: Record<string, unknown> | null;
}

function recordingFetch(routes: Record<string, FetchResponse>): {
  fetch: (path: string, options?: unknown) => FetchResponse;
  calls: RecordedCall[];
} {
  const calls: RecordedCall[] = [];
  const fetch = (path: string, options?: unknown) => {
    calls.push({
      path,
      body: options?.body ? JSON.parse(String(options.body)) : null,
    });
    for (const [prefix, response] of Object.entries(routes)) {
      if (path.startsWith(prefix)) return response;
    }
    return noMock;
  };
  return { fetch, calls };
}

function setValue(el: HTMLInputElement, value: string): void {
  el.value = value;
  el.dispatchEvent(new Event('input', { bubbles: true }));
}

// Counts constructions so the socket gate is observable.
class FakeWebSocket {
  static count = 0;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeWebSocket.count += 1;
  }
  addEventListener(): void {}
  close(): void {}
}

beforeEach(() => {
  // The store is module-level; start every test from the initial loading
  // state so identical values never skip a reactive transition.
  resetAuth();
  globalThis.WebSocket = null;
});

afterEach(() => {
  globalThis.fetch = realFetch;
  globalThis.WebSocket = realWebSocket;
});

test('fetchStatus reflects an unauthenticated session', async () => {
  globalThis.fetch = (path) =>
    path.startsWith('/api/auth/status') ? statusBody(false, true) : noMock;
  await fetchStatus();
  expect(authStatus()).toBe('unauthenticated');
  expect(authMustChange()).toBe(false);
});

test('login success establishes the session state', async () => {
  globalThis.fetch = (path) =>
    path.startsWith('/api/auth/login') ? statusBody(true, true) : noMock;
  const ok = await login('admin', '1234');
  expect(ok).toBe(true);
  expect(authStatus()).toBe('authenticated');
  expect(authMustChange()).toBe(true);
});

test('login failure leaves the session unauthenticated', async () => {
  globalThis.fetch = (path) =>
    path.startsWith('/api/auth/login')
      ? {
          ok: false,
          status: 401,
          statusText: 'Unauthorized',
          text: async () => JSON.stringify({ detail: 'invalid username or password' }),
        }
      : noMock;
  await fetchStatus();
  const ok = await login('admin', 'nope');
  expect(ok).toBe(false);
  expect(authStatus()).toBe('unauthenticated');
});

test('unauthenticated session renders the login page, no shell view', async () => {
  globalThis.fetch = (path) =>
    path.startsWith('/api/auth/status') ? statusBody(false, true) : noMock;
  const rendered = render(AppShell);
  await shellReady();
  expect(rendered.container.querySelector('[data-testid="login-form"]')).toBeTruthy();
  expect(rendered.container.querySelector('[data-testid="view-label"]')).toBeNull();
});

test('login form submit posts the credentials and shows a generic error on 401', async () => {
  const rejected = {
    ok: false,
    status: 401,
    statusText: 'Unauthorized',
    text: async () => JSON.stringify({ detail: 'invalid username or password' }),
  };
  const { fetch, calls } = recordingFetch({
    '/api/auth/status': statusBody(false, true),
    '/api/auth/login': rejected,
  });
  globalThis.fetch = fetch;
  const rendered = render(AppShell);
  await shellReady();

  setValue(
    rendered.container.querySelector('[data-testid="login-username"]') as HTMLInputElement,
    'admin',
  );
  setValue(
    rendered.container.querySelector('[data-testid="login-password"]') as HTMLInputElement,
    'nope',
  );
  (rendered.container.querySelector('[data-testid="login-submit"]') as HTMLButtonElement).click();
  await shellReady();
  // The 401 error text lands a microtask or two after the state bump; poll
  // the real condition (capped) instead of guessing a delay.
  for (
    let i = 0;
    i < 10 && !rendered.container.querySelector('[data-testid="login-error"]');
    i++
  ) {
    await null;
  }
  const loginCall = calls.find((call) => call.path.startsWith('/api/auth/login'));
  expect(loginCall?.body).toEqual({ username: 'admin', password: 'nope' });
  expect(rendered.container.querySelector('[data-testid="login-error"]')?.textContent).toBe(
    'Invalid username or password.',
  );
});

test('login success reaches the shell', async () => {
  globalThis.fetch = (path) => {
    if (path.startsWith('/api/auth/status')) return statusBody(false, true);
    if (path.startsWith('/api/auth/login')) return statusBody(true, false);
    return noMock;
  };
  const rendered = render(AppShell);
  await shellReady();
  expect(rendered.container.querySelector('[data-testid="login-form"]')).toBeTruthy();
  await login('admin', '1234');
  await null;
  expect(rendered.container.querySelector('[data-testid="login-form"]')).toBeNull();
  expect(rendered.container.querySelector('[data-testid="view-label"]')).toBeTruthy();
});

test('the credential-change gate blocks every other view until submitted', async () => {
  globalThis.fetch = (path) => {
    if (path.startsWith('/api/auth/status')) return statusBody(true, true);
    if (path.startsWith('/api/auth/change-credentials')) return statusBody(true, false);
    return noMock;
  };
  const rendered = render(AppShell);
  await shellReady();
  // The gate is up and no dashboard view has loaded.
  expect(rendered.container.querySelector('[data-testid="credentials-gate"]')).toBeTruthy();
  expect(rendered.container.querySelector('[data-testid="view-label"]')).toBeNull();

  await changeCredentials('onyx', 'hunter2');
  await null;
  expect(rendered.container.querySelector('[data-testid="credentials-gate"]')).toBeNull();
  expect(rendered.container.querySelector('[data-testid="view-label"]')).toBeTruthy();
});

test('gate submit posts the new credentials without complexity rules', async () => {
  const { fetch, calls } = recordingFetch({
    '/api/auth/status': statusBody(true, true),
    '/api/auth/change-credentials': statusBody(true, false),
  });
  globalThis.fetch = fetch;
  const rendered = render(AppShell);
  await shellReady();

  setValue(rendered.container.querySelector('[data-testid="gate-username"]') as HTMLInputElement, 'a');
  setValue(rendered.container.querySelector('[data-testid="gate-password"]') as HTMLInputElement, 'b');
  (rendered.container.querySelector('[data-testid="gate-submit"]') as HTMLButtonElement).click();
  await shellReady();
  const changeCall = calls.find((call) => call.path.startsWith('/api/auth/change-credentials'));
  expect(changeCall?.body).toEqual({ username: 'a', password: 'b' });
});

test('the queue socket only opens after the credential change', async () => {
  // The shell skips the socket under jsdom's user agent; masquerade so the
  // auth gate itself (not the environment check) is what is exercised.
  Object.defineProperty(globalThis.navigator, 'userAgent', {
    value: 'vitest',
    configurable: true,
  });
  globalThis.WebSocket = FakeWebSocket;
  globalThis.fetch = (path) => {
    if (path.startsWith('/api/auth/status')) return statusBody(true, true);
    if (path.startsWith('/api/auth/change-credentials')) return statusBody(true, false);
    return noMock;
  };
  const rendered = render(AppShell);
  await shellReady();
  expect(FakeWebSocket.count).toBe(0);

  await changeCredentials('onyx', 'hunter2');
  for (let i = 0; i < 10 && FakeWebSocket.count === 0; i++) {
    await null;
  }
  expect(FakeWebSocket.count).toBe(1);
});

test('a refused socket with a stale session bounces to the login page', async () => {
  // Server-restart scenario: the client still believes it is authenticated
  // (stale cookie), but the server has forgotten the session and refuses
  // the handshake (uvicorn logs "connection rejected (403 Forbidden)"). The
  // shell must bounce to the login page instead of retrying forever.
  Object.defineProperty(globalThis.navigator, 'userAgent', {
    value: 'vitest',
    configurable: true,
  });
  class RefusedSocket {
    static count = 0;
    private handlers: Array<{ type: string; fn: () => void }> = [];
    constructor() {
      RefusedSocket.count += 1;
      queueMicrotask(() =>
        this.handlers.filter((handler) => handler.type === 'close').forEach((handler) => handler.fn()),
      );
    }
    addEventListener(type: string, fn: () => void): void {
      this.handlers.push({ type, fn });
    }
    close(): void {}
  }
  globalThis.WebSocket = RefusedSocket;
  let statusCalls = 0;
  globalThis.fetch = (path) => {
    if (path.startsWith('/api/auth/status')) {
      statusCalls += 1;
      // The mount-time status says the session is valid; after the socket is
      // refused the server says it no longer knows it.
      return statusBody(statusCalls === 1, false);
    }
    return noMock;
  };
  const rendered = render(AppShell);
  await shellReady();
  for (let i = 0; i < 10 && RefusedSocket.count === 0; i++) {
    await null;
  }
  expect(RefusedSocket.count).toBe(1);
  // The refused handshake re-verifies the session; the shell bounces to the
  // login page and the pending retry does not reopen a refused socket.
  for (
    let i = 0;
    i < 20 && !rendered.container.querySelector('[data-testid="login-form"]');
    i++
  ) {
    await null;
  }
  expect(rendered.container.querySelector('[data-testid="login-form"]')).toBeTruthy();
  expect(authStatus()).toBe('unauthenticated');
});

test('a 401 from an API call routes to /login and drops the session', async () => {
  globalThis.fetch = (path) =>
    path.startsWith('/api/queue')
      ? {
          ok: false,
          status: 401,
          statusText: 'Unauthorized',
          text: async () => JSON.stringify({ detail: 'authentication required' }),
        }
      : noMock;
  await fetchStatus();
  let threw = false;
  try {
    await api.queue();
  } catch {
    threw = true;
  }
  expect(threw).toBe(true);
  expect(currentPath()).toBe('/login');
  expect(authStatus()).toBe('unauthenticated');
});
