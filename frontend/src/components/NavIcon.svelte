<script lang="ts">
  import type { NavIconKey } from '../lib/nav';

  let { icon, className = 'w-5 h-5' }: { icon: NavIconKey; className?: string } = $props();
</script>

{#if icon === 'discover'}
  <svg aria-hidden="true" class={className} fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
    <path stroke-linecap="round" stroke-linejoin="round" d="M12 2.75l2.6 5.9 6.4.6-4.85 4.2 1.45 6.3L12 16.4l-5.6 3.35 1.45-6.3-4.85-4.2 6.4-.6L12 2.75z" />
  </svg>
{:else if icon === 'movies'}
  <svg aria-hidden="true" class={className} fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
    <rect x="3" y="4" width="18" height="16" rx="2.5" />
    <path stroke-linecap="round" d="M7 4v16M17 4v16M3 9h4M17 9h4M3 15h4M17 15h4M7 12h10" />
  </svg>
{:else if icon === 'tv'}
  <svg aria-hidden="true" class={className} fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
    <rect x="3" y="6" width="18" height="12" rx="2.5" />
    <path stroke-linecap="round" stroke-linejoin="round" d="M8.5 3l3.5 3 3.5-3M9 21h6" />
  </svg>
{:else if icon === 'library'}
  <svg aria-hidden="true" class={className} fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
    <path stroke-linecap="round" stroke-linejoin="round" d="M4 19.5V5.5A1.5 1.5 0 015.5 4h2A1.5 1.5 0 019 5.5v14a1.5 1.5 0 01-1.5 1.5h-2A1.5 1.5 0 014 19.5zM9 19.5V7.5A1.5 1.5 0 0110.5 6h2A1.5 1.5 0 0114 7.5v12a1.5 1.5 0 01-1.5 1.5h-2A1.5 1.5 0 019 19.5zM14.5 6.5l4.2-1.2a1.2 1.2 0 011.5.85l2.1 12.2a1.2 1.2 0 01-.85 1.4l-4.2 1.2a1.2 1.2 0 01-1.5-.85L13.65 7.9a1.2 1.2 0 01.85-1.4z" />
  </svg>
{:else if icon === 'monitored'}
  <svg aria-hidden="true" class={className} fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
    <path stroke-linecap="round" stroke-linejoin="round" d="M2.5 12s3.5-6.5 9.5-6.5S21.5 12 21.5 12s-3.5 6.5-9.5 6.5S2.5 12 2.5 12z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
{:else if icon === 'queue'}
  <svg aria-hidden="true" class={className} fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
    <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v11m0 0l-4-4m4 4l4-4M4 17.5V19a2 2 0 002 2h12a2 2 0 002-2v-1.5" />
  </svg>
{:else}
  <svg aria-hidden="true" class={className} fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
    <path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
{/if}
