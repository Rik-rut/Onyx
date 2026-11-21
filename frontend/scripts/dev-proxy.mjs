// Dev HMR proxy: `npm run dev` serves the Vite dev output at http://127.0.0.1:3699
// while /api and /ws (upgrade included) go to the running Onyx FastAPI backend.
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import proxy from 'http-proxy';

const VITE_TARGET = 'http://127.0.0.1:5173';
const BACKEND_TARGET = 'http://127.0.0.1:3698';
const PROXY_PORT = 3699;
const BACKEND_PREFIXES = ['/api', '/ws'];

function target(url) {
  const path = decodeURIComponent(url.split('?')[0]);
  const backend = BACKEND_PREFIXES.some((p) => path === p || path.startsWith(p + '/'));
  return backend ? BACKEND_TARGET : VITE_TARGET;
}

spawn('vite', ['--port', '5173', '--host', '127.0.0.1'], { stdio: 'inherit', shell: true });

const p = proxy.createProxyServer({});
p.on('error', (error, req, res) => {
  res.statusCode = 502;
  res.end(`upstream failed: ${error.code}`);
});

const server = createServer((req, res) => p.web(req, res, { target: target(req.url) }));

server.on('upgrade', (req, res, headers) => {
  const socket = res;
  p.ws(req, socket, headers, { target: target(req.url) });
});

server.listen(PROXY_PORT, '127.0.0.1');
console.log(`[onyx-dev] proxy ready on http://127.0.0.1:${PROXY_PORT} (vite :5173, backend :3698)`);
