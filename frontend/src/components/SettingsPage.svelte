<!-- /settings: sectioned configuration editor wired to real /api/config fields
     (Storage & Import, Transfers & Quality, Seeding, Subtitles) with cross-section
     dirty tracking and a sticky Save / Discard bar. -->
<script lang="ts">
  import { api, ApiError } from '../lib/api';
  import type { ConfigValues } from '../lib/api';
  import { pushToast } from '../lib/stores/ui.svelte';

  type SectionKey = 'storage' | 'transfers' | 'seeding' | 'subtitles';

  interface SettingsSection {
    key: SectionKey;
    label: string;
    description: string;
  }

  const SECTIONS: SettingsSection[] = [
    {
      key: 'storage',
      label: 'Storage & Import',
      description: 'Staging directories, file import behavior, and TV season-pack preference.',
    },
    {
      key: 'transfers',
      label: 'Transfers & Quality',
      description: 'Concurrency limits, bandwidth throttling, and resolution scoring priority.',
    },
    {
      key: 'seeding',
      label: 'Seeding',
      description: 'Control how Transmission handles completed torrents after library import.',
    },
    {
      key: 'subtitles',
      label: 'Subtitles',
      description: 'Automatic subtitle fetching and strict language priority ordering.',
    },
  ];

  const RESOLUTION_OPTIONS = ['2160p', '1080p', '720p', '480p'] as const;

  interface EditableConfig {
    download_root: string;
    library_root: string;
    import_mode: string;
    prefer_season_packs: boolean;
    max_concurrent_downloads: number;
    max_download_speed_kbps: number;
    max_upload_speed_kbps: number;
    resolutions: string[];
    seeding_policy: string;
    subtitles_enabled: boolean;
    subtitles_forced_only: boolean;
    subtitle_languages: string;
  }

  function toEditable(cfg: ConfigValues): EditableConfig {
    return {
      download_root: cfg.download_root ?? '',
      library_root: cfg.library_root ?? '',
      import_mode: cfg.import_mode ?? 'hardlink',
      prefer_season_packs: Boolean(cfg.prefer_season_packs),
      max_concurrent_downloads: Number(cfg.max_concurrent_downloads ?? 3),
      max_download_speed_kbps: Number(cfg.max_download_speed_kbps ?? 0),
      max_upload_speed_kbps: Number(cfg.max_upload_speed_kbps ?? 0),
      resolutions: Array.isArray(cfg.resolutions) ? [...cfg.resolutions] : ['1080p', '720p'],
      seeding_policy: cfg.seeding_policy ?? 'ratio',
      subtitles_enabled: Boolean(cfg.subtitles_enabled ?? true),
      subtitles_forced_only: Boolean(cfg.subtitles_forced_only ?? false),
      subtitle_languages: Array.isArray(cfg.subtitle_languages) ? cfg.subtitle_languages.join(', ') : 'en',
    };
  }

  function cloneEditable(src: EditableConfig): EditableConfig {
    return { ...src, resolutions: [...src.resolutions] };
  }

  function parseLanguages(raw: string): string[] {
    return raw
      .split(',')
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean);
  }

  function diffKeys(saved: EditableConfig | null, pending: EditableConfig | null): Array<keyof EditableConfig> {
    if (!saved || !pending) return [];
    const keys: Array<keyof EditableConfig> = [
      'download_root',
      'library_root',
      'import_mode',
      'prefer_season_packs',
      'max_concurrent_downloads',
      'max_download_speed_kbps',
      'max_upload_speed_kbps',
      'resolutions',
      'seeding_policy',
      'subtitles_enabled',
      'subtitles_forced_only',
      'subtitle_languages',
    ];
    return keys.filter((key) => {
      if (key === 'resolutions') {
        return JSON.stringify(saved.resolutions) !== JSON.stringify(pending.resolutions);
      }
      if (key === 'subtitle_languages') {
        return JSON.stringify(parseLanguages(saved.subtitle_languages)) !== JSON.stringify(parseLanguages(pending.subtitle_languages));
      }
      return saved[key] !== pending[key];
    });
  }

  const box = $state({
    loading: null as null | Promise<void>,
    abandoned: false,
    loaded: false,
    error: null as string | null,
    saved: null as EditableConfig | null,
    pending: null as EditableConfig | null,
    active: 'storage' as SectionKey,
    saving: false,
    saveError: null as string | null,
  });

  $effect(() => ensureLoaded());

  function ensureLoaded(): void {
    if (box.loading === null && !box.loaded && !box.abandoned) {
      box.loading = load();
    }
  }

  function failureText(failure: unknown): string {
    return failure instanceof ApiError ? failure.detail : String(failure);
  }

  async function load(): Promise<void> {
    try {
      const payload = await api.config();
      const normalized = toEditable(payload);
      box.saved = cloneEditable(normalized);
      box.pending = cloneEditable(normalized);
      box.loaded = true;
      box.error = null;
      box.abandoned = false;
    } catch (failure) {
      box.error = failureText(failure);
      box.abandoned = true;
    }
    box.loading = null;
  }

  function retry(): void {
    box.abandoned = false;
    box.loading = null;
    ensureLoaded();
  }

  const changedFields = $derived(diffKeys(box.saved, box.pending));
  const dirty = $derived(changedFields.length > 0);
  const activeSection = $derived(SECTIONS.find((section) => section.key === box.active) ?? SECTIONS[0]);

  function toggleResolution(res: string): void {
    if (!box.pending) return;
    const current = box.pending.resolutions;
    const next = current.includes(res) ? current.filter((item) => item !== res) : [...current, res];
    box.pending.resolutions = next;
    box.saveError = null;
  }

  function discard(): void {
    if (!box.saved) return;
    box.pending = cloneEditable(box.saved);
    box.saveError = null;
  }

  async function save(): Promise<void> {
    if (!dirty || box.saving || !box.pending) return;
    const payload: Record<string, unknown> = {};
    for (const key of changedFields) {
      if (key === 'subtitle_languages') {
        payload[key] = parseLanguages(box.pending.subtitle_languages);
      } else if (key === 'resolutions') {
        payload[key] = [...box.pending.resolutions];
      } else {
        payload[key] = box.pending[key];
      }
    }
    box.saving = true;
    box.saveError = null;
    try {
      const updated = await api.saveConfig(payload);
      const nextBaseline = updated && typeof updated.download_root === 'string'
        ? toEditable(updated)
        : cloneEditable(box.pending);
      box.saved = cloneEditable(nextBaseline);
      box.pending = cloneEditable(nextBaseline);
      pushToast({ message: 'Settings saved', kind: 'success' });
    } catch (failure) {
      box.saveError = failureText(failure);
      pushToast({ message: `Failed to save settings: ${box.saveError}`, kind: 'error' });
    } finally {
      box.saving = false;
    }
  }
</script>

<div class="flex flex-col gap-6" data-testid="settings-page">
  <div>
    <h1 class="text-2xl sm:text-3xl font-black text-white tracking-tight">Settings</h1>
    <p class="mt-1 text-xs sm:text-sm text-slate-400">
      Configure Onyx storage paths, transfer limits, seeding rules, and automatic subtitles.
    </p>
  </div>

  {#if box.error && !box.loaded}
    <div
      class="rounded-2xl p-6 bg-onyx-surface border border-amber-700/40 flex flex-wrap items-center justify-between gap-4"
      data-testid="settings-error"
      role="status"
      aria-live="polite"
    >
      <div class="space-y-1">
        <p class="text-sm font-semibold text-amber-300" data-testid="settings-error-message">{box.error}</p>
        <p class="text-xs text-slate-400" data-testid="settings-save-note">No changes posted.</p>
      </div>
      <button
        class="rounded-xl px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold cursor-pointer"
        type="button"
        data-testid="settings-retry"
        onclick={() => retry()}
      >
        Retry now
      </button>
    </div>
  {:else if !box.loaded || !box.pending}
    <div class="rounded-2xl p-6 bg-onyx-surface border border-onyx-border/70 space-y-4" data-testid="settings-loading" aria-live="polite">
      <span class="sr-only">Loading settings…</span>
      <div class="h-5 w-48 rounded skeleton-pulse"></div>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="h-14 rounded-xl skeleton-pulse"></div>
        <div class="h-14 rounded-xl skeleton-pulse"></div>
      </div>
    </div>
  {:else}
    <div class="flex flex-col lg:flex-row items-start gap-6">
      <!-- Vertical Section Tabs -->
      <nav
        class="w-full lg:w-56 shrink-0 flex flex-row lg:flex-col gap-1.5 overflow-x-auto no-scrollbar"
        data-testid="settings-section-nav"
        aria-label="Settings sections"
      >
        {#each SECTIONS as section (section.key)}
          {@const active = box.active === section.key}
          <button
            class="shrink-0 rounded-xl px-4 py-2.5 text-xs sm:text-sm font-semibold text-left border transition-colors cursor-pointer {active
              ? 'bg-indigo-500/15 text-white border-indigo-500/40'
              : 'bg-onyx-surface/70 text-slate-400 border-onyx-border/70 hover:text-white hover:border-slate-600'}"
            type="button"
            data-testid={`settings-nav-${section.key}`}
            data-section={section.key}
            data-active={active}
            aria-current={active ? 'page' : undefined}
            onclick={() => (box.active = section.key)}
          >
            {section.label}
          </button>
        {/each}
      </nav>

      <!-- Active Section Panel -->
      <section
        class="flex-1 w-full rounded-2xl p-5 sm:p-6 bg-onyx-surface border border-onyx-border/80 shadow-lg shadow-black/30 space-y-6"
        data-testid="settings-section"
        data-section={activeSection.key}
        aria-label={activeSection.label}
      >
        <div class="border-b border-onyx-border/70 pb-4">
          <h2 class="text-base sm:text-lg font-bold text-white">{activeSection.label}</h2>
          <p class="mt-1 text-xs text-slate-400">{activeSection.description}</p>
        </div>

        {#if box.active === 'storage'}
          <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
            <div class="space-y-1.5" data-testid="setting-row" data-field="download_root">
              <label for="downloadRoot" class="block text-xs font-semibold text-slate-300">Download Staging Root</label>
              <input
                id="downloadRoot"
                type="text"
                data-testid="input-download_root"
                bind:value={box.pending.download_root}
                class="w-full rounded-xl px-3.5 py-2.5 bg-onyx-obsidian border border-onyx-border text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div class="space-y-1.5" data-testid="setting-row" data-field="library_root">
              <label for="libraryRoot" class="block text-xs font-semibold text-slate-300">Media Library Root</label>
              <input
                id="libraryRoot"
                type="text"
                data-testid="input-library_root"
                bind:value={box.pending.library_root}
                class="w-full rounded-xl px-3.5 py-2.5 bg-onyx-obsidian border border-onyx-border text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div class="space-y-1.5" data-testid="setting-row" data-field="import_mode">
              <label for="importMode" class="block text-xs font-semibold text-slate-300">Import Mode</label>
              <select
                id="importMode"
                data-testid="select-import_mode"
                bind:value={box.pending.import_mode}
                class="w-full rounded-xl px-3.5 py-2.5 bg-onyx-obsidian border border-onyx-border text-sm text-white focus:outline-none focus:border-indigo-500"
              >
                <option value="hardlink">hardlink — link files &amp; keep seeding (recommended)</option>
                <option value="copy">copy — duplicate files &amp; keep seeding</option>
                <option value="move">move — relocate files &amp; stop seeding</option>
              </select>
            </div>

            <div
              class="flex items-center justify-between gap-4 rounded-xl p-4 bg-onyx-obsidian/70 border border-onyx-border/80"
              data-testid="setting-row"
              data-field="prefer_season_packs"
            >
              <div>
                <p class="text-xs sm:text-sm font-semibold text-white">Prefer Season Packs</p>
                <p class="text-[11px] text-slate-400 mt-0.5">Prioritize full-season releases over single episodes</p>
              </div>
              <button
                type="button"
                role="switch"
                aria-label="Prefer Season Packs"
                aria-checked={box.pending.prefer_season_packs}
                data-testid="toggle-prefer_season_packs"
                class="relative inline-flex h-6 w-11 shrink-0 rounded-full border transition-colors cursor-pointer {box.pending.prefer_season_packs
                  ? 'bg-indigo-600 border-indigo-500'
                  : 'bg-slate-800 border-slate-700'}"
                onclick={() => {
                  if (box.pending) box.pending.prefer_season_packs = !box.pending.prefer_season_packs;
                }}
              >
                <span
                  class="pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow transition-transform {box.pending.prefer_season_packs
                    ? 'translate-x-5'
                    : 'translate-x-0.5'}"
                ></span>
              </button>
            </div>
          </div>
        {:else if box.active === 'transfers'}
          <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
            <div class="space-y-1.5" data-testid="setting-row" data-field="max_concurrent_downloads">
              <label for="maxDownloads" class="block text-xs font-semibold text-slate-300">Max Concurrent Downloads</label>
              <input
                id="maxDownloads"
                type="number"
                min="1"
                max="20"
                data-testid="input-max_concurrent_downloads"
                bind:value={box.pending.max_concurrent_downloads}
                class="w-full rounded-xl px-3.5 py-2.5 bg-onyx-obsidian border border-onyx-border text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div class="space-y-1.5" data-testid="setting-row" data-field="max_download_speed_kbps">
              <label for="maxDownSpeed" class="block text-xs font-semibold text-slate-300">Max Download Speed (KB/s, 0 = unlimited)</label>
              <input
                id="maxDownSpeed"
                type="number"
                min="0"
                data-testid="input-max_download_speed_kbps"
                bind:value={box.pending.max_download_speed_kbps}
                class="w-full rounded-xl px-3.5 py-2.5 bg-onyx-obsidian border border-onyx-border text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div class="space-y-1.5" data-testid="setting-row" data-field="max_upload_speed_kbps">
              <label for="maxUpSpeed" class="block text-xs font-semibold text-slate-300">Max Upload Speed (KB/s, 0 = unlimited)</label>
              <input
                id="maxUpSpeed"
                type="number"
                min="0"
                data-testid="input-max_upload_speed_kbps"
                bind:value={box.pending.max_upload_speed_kbps}
                class="w-full rounded-xl px-3.5 py-2.5 bg-onyx-obsidian border border-onyx-border text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div class="md:col-span-2 space-y-2" data-testid="setting-row" data-field="resolutions">
              <span class="block text-xs font-semibold text-slate-300">Preferred Resolutions</span>
              <div class="flex flex-wrap gap-2" role="group" aria-label="Preferred resolutions">
                {#each RESOLUTION_OPTIONS as res}
                  {@const selected = box.pending.resolutions.includes(res)}
                  <button
                    type="button"
                    data-testid={`res-${res}`}
                    aria-pressed={selected}
                    class="rounded-xl px-3.5 py-2 text-xs font-semibold uppercase border transition-colors cursor-pointer {selected
                      ? 'bg-indigo-600 text-white border-indigo-500'
                      : 'bg-onyx-obsidian text-slate-400 border-onyx-border hover:text-white hover:border-slate-500'}"
                    onclick={() => toggleResolution(res)}
                  >
                    {res === '2160p' ? '4K / 2160p' : res}
                  </button>
                {/each}
              </div>
              <p class="text-[11px] text-slate-500">Preferred resolutions are prioritized when scoring candidate releases.</p>
            </div>
          </div>
        {:else if box.active === 'seeding'}
          <div class="max-w-lg space-y-2" data-testid="setting-row" data-field="seeding_policy">
            <label for="seedingPolicy" class="block text-xs font-semibold text-slate-300">Seeding Policy</label>
            <select
              id="seedingPolicy"
              data-testid="select-seeding_policy"
              bind:value={box.pending.seeding_policy}
              class="w-full rounded-xl px-3.5 py-2.5 bg-onyx-obsidian border border-onyx-border text-sm text-white focus:outline-none focus:border-indigo-500"
            >
              <option value="ratio">ratio — stop seeding once target ratio is reached</option>
              <option value="time">time — stop seeding after configured duration</option>
              <option value="manual">manual — keep seeding until manually removed</option>
              <option value="remove_on_import">remove_on_import — delete torrent data immediately after copy import</option>
            </select>
            <p class="text-[11px] text-slate-500">
              Note: <code class="text-slate-300">remove_on_import</code> requires copy import mode so library hardlinks are never deleted.
            </p>
          </div>
        {:else}
          <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
            <div
              class="flex items-center justify-between gap-4 rounded-xl p-4 bg-onyx-obsidian/70 border border-onyx-border/80"
              data-testid="setting-row"
              data-field="subtitles_enabled"
            >
              <div>
                <p class="text-xs sm:text-sm font-semibold text-white">Automatic Subtitle Fetching</p>
                <p class="text-[11px] text-slate-400 mt-0.5">Download matching .srt subtitles after import</p>
              </div>
              <button
                type="button"
                role="switch"
                aria-label="Automatic Subtitle Fetching"
                aria-checked={box.pending.subtitles_enabled}
                data-testid="toggle-subtitles_enabled"
                class="relative inline-flex h-6 w-11 shrink-0 rounded-full border transition-colors cursor-pointer {box.pending.subtitles_enabled
                  ? 'bg-indigo-600 border-indigo-500'
                  : 'bg-slate-800 border-slate-700'}"
                onclick={() => {
                  if (box.pending) box.pending.subtitles_enabled = !box.pending.subtitles_enabled;
                }}
              >
                <span
                  class="pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow transition-transform {box.pending.subtitles_enabled
                    ? 'translate-x-5'
                    : 'translate-x-0.5'}"
                ></span>
              </button>
            </div>

            <div
              class="flex items-center justify-between gap-4 rounded-xl p-4 bg-onyx-obsidian/70 border border-onyx-border/80"
              data-testid="setting-row"
              data-field="subtitles_forced_only"
            >
              <div>
                <p class="text-xs sm:text-sm font-semibold text-white">Forced / Foreign-Only</p>
                <p class="text-[11px] text-slate-400 mt-0.5">Only fetch forced subtitle tracks</p>
              </div>
              <button
                type="button"
                role="switch"
                aria-label="Forced / Foreign-Only Subtitles"
                aria-checked={box.pending.subtitles_forced_only}
                data-testid="toggle-subtitles_forced_only"
                class="relative inline-flex h-6 w-11 shrink-0 rounded-full border transition-colors cursor-pointer {box.pending.subtitles_forced_only
                  ? 'bg-indigo-600 border-indigo-500'
                  : 'bg-slate-800 border-slate-700'}"
                onclick={() => {
                  if (box.pending) box.pending.subtitles_forced_only = !box.pending.subtitles_forced_only;
                }}
              >
                <span
                  class="pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow transition-transform {box.pending.subtitles_forced_only
                    ? 'translate-x-5'
                    : 'translate-x-0.5'}"
                ></span>
              </button>
            </div>

            <div class="md:col-span-2 space-y-1.5" data-testid="setting-row" data-field="subtitle_languages">
              <label for="subtitleLanguages" class="block text-xs font-semibold text-slate-300">
                Preferred Languages (priority order, comma-separated)
              </label>
              <input
                id="subtitleLanguages"
                type="text"
                placeholder="en, es"
                data-testid="input-subtitle_languages"
                bind:value={box.pending.subtitle_languages}
                class="w-full rounded-xl px-3.5 py-2.5 bg-onyx-obsidian border border-onyx-border text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
              />
              <p class="text-[11px] text-slate-500">
                Onyx evaluates languages in priority order and downloads the first available match.
              </p>
            </div>
          </div>
        {/if}
      </section>
    </div>

    {#if box.saveError}
      <p class="rounded-xl px-4 py-3 bg-rose-950/40 border border-rose-800/50 text-xs text-rose-300" data-testid="settings-save-error" role="status">
        {box.saveError}
      </p>
    {/if}

    <!-- Sticky Save / Discard Action Bar -->
    <div
      class="sticky bottom-16 lg:bottom-4 z-20 flex flex-wrap items-center justify-between gap-3 rounded-2xl px-5 py-3.5 border backdrop-blur-md shadow-xl shadow-black/50 transition-colors {dirty
        ? 'bg-onyx-raised/95 border-indigo-500/45'
        : 'bg-onyx-surface/90 border-onyx-border/80'}"
      data-testid="settings-actions"
      data-dirty={dirty}
    >
      <div class="flex items-center gap-2.5 text-xs sm:text-sm">
        <span
          class="w-2 h-2 rounded-full {dirty ? 'bg-amber-400' : 'bg-emerald-400'}"
          aria-hidden="true"
        ></span>
        <span class="{dirty ? 'text-amber-200 font-semibold' : 'text-slate-400'}" data-testid="settings-dirty-state">
          {dirty ? `${changedFields.length} unsaved change${changedFields.length === 1 ? '' : 's'}` : 'All changes saved'}
        </span>
      </div>

      <div class="flex items-center gap-2.5">
        <button
          class="rounded-xl px-4 py-2 bg-onyx-obsidian hover:bg-slate-800 border border-onyx-border text-xs sm:text-sm font-semibold text-slate-300 hover:text-white disabled:opacity-40 transition-colors cursor-pointer"
          type="button"
          data-testid="discard-settings"
          disabled={!dirty || box.saving}
          onclick={() => discard()}
        >
          Discard
        </button>
        <button
          class="rounded-xl px-5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-xs sm:text-sm font-semibold text-white shadow-md shadow-indigo-950/60 transition-colors cursor-pointer"
          type="button"
          data-testid="save-settings"
          disabled={!dirty || box.saving}
          onclick={() => void save()}
        >
          {box.saving ? 'Saving…' : 'Save Settings'}
        </button>
      </div>
    </div>
  {/if}
</div>
