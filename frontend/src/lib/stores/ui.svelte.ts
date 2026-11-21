// Shell-level UI state: sidebar preference (persisted), recent searches,
// toasts, global confirmation dialog, command palette, and Release Drawer state.
declare const globalThis: {
  setTimeout: (callback: () => void, ms: number) => ReturnType<typeof setTimeout>;
  clearTimeout?: (id: ReturnType<typeof setTimeout>) => void;
  localStorage?: {
    getItem: (key: string) => string | null;
    setItem: (key: string, value: string) => void;
  };
};

export interface Toast {
  message: string;
  kind: 'info' | 'success' | 'error';
  actionLabel?: string;
  actionPath?: string;
}

export interface Confirmation {
  id: string;
  title: string;
  message: string;
  kind: 'danger' | 'duplicate';
  confirmLabel?: string;
  actionPath?: string;
}

export interface DrawerState {
  open: boolean;
  scope: 'movie' | 'tv-season' | 'tv-episode';
  target: Record<string, unknown>;
  releases: unknown[];
  loading: boolean;
}

const COLLAPSE_KEY = 'onyx.sidebar-collapsed';
const RECENT_KEY = 'onyx.recent-searches';
export const RECENT_LIMIT = 8;

const memoryStorage = new Map<string, string>();

function readValue(key: string): string | null {
  const storage = globalThis.localStorage;
  if (!storage) return memoryStorage.get(key) ?? null;
  try {
    return storage.getItem(key);
  } catch {
    return memoryStorage.get(key) ?? null;
  }
}

function writeValue(key: string, value: string): void {
  memoryStorage.set(key, value);
  const storage = globalThis.localStorage;
  if (!storage) return;
  try {
    storage.setItem(key, value);
  } catch {
    // Private browsing / restricted storage fallback.
  }
}

const shell = $state({
  collapsed: readValue(COLLAPSE_KEY) === 'true',
  recent: (readValue(RECENT_KEY) ?? '').split('\n').filter(Boolean),
  toasts: [] as Toast[],
  confirmation: null as Confirmation | null,
  palette: { open: false, query: '' },
  drawer: null as DrawerState | null,
});

export function sidebarCollapsed(): boolean {
  return shell.collapsed;
}

export function setSidebarCollapsed(collapsed: boolean): void {
  shell.collapsed = collapsed;
  writeValue(COLLAPSE_KEY, String(collapsed));
}

export function recentSearches(): string[] {
  return shell.recent;
}

export function rememberSearch(query: string): void {
  const trimmed = query.trim();
  if (!trimmed) return;
  shell.recent = [trimmed, ...shell.recent.filter((item) => item !== trimmed)].slice(0, RECENT_LIMIT);
  writeValue(RECENT_KEY, shell.recent.join('\n'));
}

export function toasts(): Toast[] {
  return shell.toasts;
}

export function pushToast(toast: Toast): void {
  shell.toasts = [...shell.toasts.slice(-3), toast];
}

export function dismissToast(index: number): void {
  shell.toasts = shell.toasts.filter((_, i) => i !== index);
}

export function clearToasts(): void {
  shell.toasts = [];
}

let toastTimer: ReturnType<typeof setTimeout> | null = null;

export function dismissToastsAfter(ms: number): void {
  if (toastTimer !== null) {
    globalThis.clearTimeout?.(toastTimer);
    toastTimer = null;
  }
  if (shell.toasts.length === 0) return;
  toastTimer = globalThis.setTimeout(() => {
    toastTimer = null;
    clearToasts();
  }, ms);
}

export function confirmation(): Confirmation | null {
  return shell.confirmation;
}

const awaitingAnswer: Record<string, (approved: boolean) => void> = {};

export function askConfirmation(details: Confirmation): Promise<boolean> {
  shell.confirmation = details;
  const { promise, resolve } = Promise.withResolvers<boolean>();
  awaitingAnswer[details.id] = resolve;
  return promise;
}

export function answerConfirmation(approved: boolean): Confirmation | null {
  const pending = shell.confirmation;
  if (!pending) return null;
  const resolve = awaitingAnswer[pending.id];
  delete awaitingAnswer[pending.id];
  shell.confirmation = null;
  resolve?.(approved);
  return pending;
}

export function palette(): { open: boolean; query: string } {
  return shell.palette;
}

export function setPalette(open: boolean, query: string): void {
  shell.palette = { open, query };
}

export function drawer(): DrawerState | null {
  return shell.drawer;
}

export function openDrawer(
  scope: 'movie' | 'tv-season' | 'tv-episode',
  target: Record<string, unknown>,
  loading = true,
): void {
  shell.drawer = { open: true, scope, target, releases: [], loading };
}

export function setDrawerReleases(releases: unknown[], loading = false): void {
  if (!shell.drawer) return;
  shell.drawer = {
    open: shell.drawer.open,
    scope: shell.drawer.scope,
    target: shell.drawer.target,
    releases,
    loading,
  };
}

export function closeDrawer(): void {
  shell.drawer = null;
}
