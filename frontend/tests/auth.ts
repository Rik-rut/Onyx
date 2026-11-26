// Shared fetch-mock helper: wraps a per-test fetch so /api/auth/status reports
// an authenticated session, keeping AppShell's auth gate out of the way for
// tests that render the shell without exercising login.
export type FetchResponse = {
  ok: boolean;
  status: number;
  statusText: string;
  text: () => Promise<string>;
};

export type FetchMock = (path: string, options?: unknown) => FetchResponse;

export function authenticatedFetch(inner: FetchMock): FetchMock {
  return (path, options) => {
    if (path.startsWith('/api/auth/status')) {
      return {
        ok: true,
        status: 200,
        statusText: 'OK',
        text: async () =>
          JSON.stringify({
            authenticated: true,
            username: 'admin',
            must_change_credentials: false,
          }),
      };
    }
    return inner(path, options);
  };
}
