// Post-build step: copy the Vite output (frontend/dist) into
// src/arr/web/static/dist, where the FastAPI server serves it, and fail loudly
// if any external CDN reference leaked into the bundle.
import { cpSync, readFileSync, readdirSync, globSync, rmSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve('dist');
const DIST = path.resolve('../src/arr/web/static/dist');
const CDN_MARKERS = ['//cdn.', 'unpkg.', 'jsdelivr', 'cdnjs.', 'googleapis.', 'googletagmanager'];

if (!globSync('index.html', { cwd: SRC }).length) {
  throw new Error(`frontend/dist/index.html missing — vite build must emit the SPA entry document`);
}

rmSync(DIST, { recursive: true, force: true, dir: true });
cpSync(SRC, DIST, { recursive: true });

const files = globSync('**/*.{js,css,html}', { cwd: DIST }).map((f) => path.join(DIST, f));
for (const file of files) {
  const text = readFileSync(file, 'utf8');
  const hit = CDN_MARKERS.find((marker) => text.includes(marker));
  if (hit) throw new Error(`CDN reference "${hit}" found in ${path.basename(file)} — bundle must be offline-safe`);
}

const indexHtml = readFileSync(path.join(DIST, 'index.html'), 'utf8');
const external = indexHtml.match(/(?:src|href)="https?:\/\/[^"]*"/g) ?? [];
if (external.length) throw new Error(`index.html references external URLs: ${external.join(', ')}`);

console.log(`[finalize] copied ${readdirSync(path.join(DIST, 'assets')).length} assets to ${DIST}`);
