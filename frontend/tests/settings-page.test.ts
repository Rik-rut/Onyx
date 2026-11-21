import { expect, test } from 'vitest';
import { fireEvent, render } from '@testing-library/svelte';
import { flushSync } from 'svelte';
import SettingsPage from '../src/components/SettingsPage.svelte';
import type { ConfigValues } from '../src/lib/api';

declare const globalThis: {
  fetch: (
    path: string,
    options?: { method?: string; headers?: Record<string, string>; body?: string },
  ) => {
    ok: boolean;
    status: number;
    statusText: string;
    text: () => Promise<string>;
  };
};

const realFetch = globalThis.fetch;

const settle = async () => {
  for (let round = 0; round < 40; round += 1) await null;
};

const INITIAL_CONFIG: ConfigValues = {
  download_root: '/downloads',
  library_root: '/downloads',
  import_mode: 'hardlink',
  prefer_season_packs: true,
  max_concurrent_downloads: 3,
  max_download_speed_kbps: 0,
  max_upload_speed_kbps: 0,
  resolutions: ['1080p', '720p'],
  seeding_policy: 'ratio',
  subtitles_enabled: true,
  subtitles_forced_only: false,
  subtitle_languages: ['en', 'es'],
};

const SECTION_LABELS = ['Storage & Import', 'Transfers & Quality', 'Seeding', 'Subtitles'];
const SECTION_FIELDS: Record<string, string[]> = {
  storage: ['download_root', 'library_root', 'import_mode', 'prefer_season_packs'],
  transfers: ['max_concurrent_downloads', 'max_download_speed_kbps', 'max_upload_speed_kbps', 'resolutions'],
  seeding: ['seeding_policy'],
  subtitles: ['subtitles_enabled', 'subtitles_forced_only', 'subtitle_languages'],
};

interface Call {
  method: string;
  path: string;
  body?: Record<string, unknown>;
}

let calls: Call[] = [];

function ok(body: unknown) {
  return { ok: true, status: 200, statusText: 'OK', text: async () => JSON.stringify(body) };
}

function fail(status: number, detail: string) {
  return {
    ok: false,
    status,
    statusText: status === 409 ? 'Conflict' : 'Internal Server Error',
    text: async () => JSON.stringify({ detail }),
  };
}

function serveOk(): void {
  globalThis.fetch = (path: string, options?: { method?: string; body?: string }) => {
    const method = options?.method ?? 'GET';
    const body = options?.body ? (JSON.parse(options.body) as Record<string, unknown>) : undefined;
    calls.push({ method, path, body });
    if (method === 'PUT') return ok({ status: 'saved', config: { ...INITIAL_CONFIG, ...body } });
    return ok(INITIAL_CONFIG);
  };
}

function element(container: HTMLElement, testId: string): HTMLElement {
  return container.querySelector(`[data-testid="${testId}"]`) as HTMLElement;
}

function click(node: HTMLElement | null): void {
  if (!node) throw new Error('missing element to click');
  flushSync(() => node.click());
}

function fields(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('[data-testid="setting-row"]')).map(
    (row) => row.getAttribute('data-field') ?? '',
  );
}

function puts(): Call[] {
  return calls.filter((call) => call.method === 'PUT');
}

test('sections edit real /api/config fields, track dirty state across tabs, discard resets, and save posts one PUT', async () => {
  calls = [];
  serveOk();
  const rendered = render(SettingsPage);
  await settle();
  const container = rendered.container;

  const navButtons = Array.from(container.querySelectorAll('[data-testid="settings-section-nav"] button'));
  expect(navButtons.map((button) => button.textContent?.trim())).toEqual(SECTION_LABELS);
  expect(navButtons.map((button) => button.getAttribute('data-active'))).toEqual(['true', 'false', 'false', 'false']);
  expect(fields(container)).toEqual(SECTION_FIELDS.storage);
  expect(puts()).toEqual([]);

  for (const key of ['transfers', 'seeding', 'subtitles']) {
    click(element(container, `settings-nav-${key}`));
    expect(element(container, `settings-nav-${key}`).getAttribute('data-active')).toBe('true');
    expect(element(container, 'settings-section').getAttribute('data-section')).toBe(key);
    expect(fields(container)).toEqual(SECTION_FIELDS[key]);
  }
  click(element(container, 'settings-nav-storage'));

  // Toggle prefer_season_packs and edit resolutions across tabs without saving yet.
  click(element(container, 'toggle-prefer_season_packs'));
  expect(element(container, 'settings-actions').getAttribute('data-dirty')).toBe('true');
  expect(element(container, 'settings-dirty-state').textContent?.trim()).toBe('1 unsaved change');
  expect(element(container, 'discard-settings').hasAttribute('disabled')).toBe(false);
  expect(puts()).toEqual([]);

  click(element(container, 'settings-nav-transfers'));
  click(element(container, 'res-2160p'));
  expect(element(container, 'settings-dirty-state').textContent?.trim()).toBe('2 unsaved changes');
  expect(puts()).toEqual([]);

  // Discard reverts edits across all sections.
  click(element(container, 'discard-settings'));
  expect(element(container, 'settings-actions').getAttribute('data-dirty')).toBe('false');
  expect(element(container, 'settings-dirty-state').textContent?.trim()).toBe('All changes saved');
  expect(element(container, 'res-2160p').getAttribute('aria-pressed')).toBe('false');
  expect(puts()).toEqual([]);

  // Edit prefer_season_packs + subtitle_languages, then Save in one PUT.
  click(element(container, 'settings-nav-storage'));
  click(element(container, 'toggle-prefer_season_packs'));
  click(element(container, 'settings-nav-subtitles'));
  const langInput = element(container, 'input-subtitle_languages') as HTMLInputElement;
  await fireEvent.input(langInput, { target: { value: 'en, ja, fr' } });
  flushSync();
  click(element(container, 'save-settings'));
  await settle();

  expect(puts()).toHaveLength(1);
  expect(puts()[0].path).toBe('/api/config');
  expect(puts()[0].body).toEqual({
    prefer_season_packs: false,
    subtitle_languages: ['en', 'ja', 'fr'],
  });
  expect(element(container, 'settings-actions').getAttribute('data-dirty')).toBe('false');
  globalThis.fetch = realFetch;
});

test('a 500 on /api/config shows the detail and posts nothing', async () => {
  calls = [];
  globalThis.fetch = (path: string, options?: { method?: string; body?: string }) => {
    calls.push({ method: options?.method ?? 'GET', path });
    return fail(500, 'Settings unavailable: config backend offline');
  };

  const rendered = render(SettingsPage);
  await settle();

  expect(element(rendered.container, 'settings-error-message').textContent?.trim()).toBe(
    'Settings unavailable: config backend offline',
  );
  expect(element(rendered.container, 'settings-save-note').textContent).toContain('No changes posted');
  expect(rendered.container.querySelectorAll('[data-testid="setting-row"]')).toHaveLength(0);
  expect(rendered.container.querySelector('[data-testid="settings-section-nav"]')).toBeNull();
  expect(puts()).toEqual([]);
  globalThis.fetch = realFetch;
});

test('a 409 on /api/config degrades the same way', async () => {
  calls = [];
  globalThis.fetch = (path: string, options?: { method?: string; body?: string }) => {
    calls.push({ method: options?.method ?? 'GET', path });
    return fail(409, 'Settings locked: confirm the pending change first');
  };

  const rendered = render(SettingsPage);
  await settle();

  expect(element(rendered.container, 'settings-error-message').textContent?.trim()).toBe(
    'Settings locked: confirm the pending change first',
  );
  expect(rendered.container.querySelectorAll('[data-testid="setting-row"]')).toHaveLength(0);
  expect(puts()).toEqual([]);
  globalThis.fetch = realFetch;
});
