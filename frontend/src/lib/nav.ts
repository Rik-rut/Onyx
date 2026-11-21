// Shared navigation table: the sidebar rail and the mobile bottom bar render
// from this single source of truth so labels, paths, and icons never drift.
export type NavIconKey = 'discover' | 'movies' | 'tv' | 'library' | 'monitored' | 'queue' | 'settings';

export interface NavItem {
  label: string;
  shortLabel: string;
  path: string;
  icon: NavIconKey;
}

export const NAV_SECTIONS: Array<{
  key: 'browse' | 'media' | 'system';
  label: string;
  items: NavItem[];
}> = [
  {
    key: 'browse',
    label: 'Browse',
    items: [
      { label: 'Discover', shortLabel: 'Discover', path: '/', icon: 'discover' },
      { label: 'Movies', shortLabel: 'Movies', path: '/movies', icon: 'movies' },
      { label: 'TV Shows', shortLabel: 'TV', path: '/tv', icon: 'tv' },
    ],
  },
  {
    key: 'media',
    label: 'My Media',
    items: [
      { label: 'Library', shortLabel: 'Library', path: '/library', icon: 'library' },
      { label: 'Monitored', shortLabel: 'Tracked', path: '/monitored', icon: 'monitored' },
      { label: 'Queue', shortLabel: 'Queue', path: '/queue', icon: 'queue' },
    ],
  },
  {
    key: 'system',
    label: 'System',
    items: [{ label: 'Settings', shortLabel: 'Settings', path: '/settings', icon: 'settings' }],
  },
];
