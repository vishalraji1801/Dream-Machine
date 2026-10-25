import cors from 'cors';
import express from 'express';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { record } from './activity.js';
import { authRouter } from './authRoutes.js';
import { router } from './routes.js';
import { requireUnlocked } from './security.js';
import { ValidationError } from './validate.js';

const here = dirname(fileURLToPath(import.meta.url));

/*
 * Maps the write endpoints onto the feature keys in the activity registry, so the
 * log reflects what was actually done rather than what the UI claimed. Reads are
 * deliberately not logged: refreshing fires several GETs per action and would
 * drown the signal.
 */
const MUTATION_FEATURES = [
  [/^\/transactions/, 'lenden', 'transactions'],
  [/^\/npa/, 'lenden', 'npa'],
  [/^\/loan-entries/, 'loan', 'entries'],
  [/^\/loan-offers/, 'loan', 'comparator'],
  [/^\/loan-settings/, 'loan', 'entries'],
  [/^\/expenses/, 'everyday', 'log'],
  [/^\/import$/, 'data', 'import'],
  [/^\/expenses-import/, 'data', 'import'],
  [/^\/loan-import/, 'data', 'import'],
];

function recordMutations(req, res, next) {
  if (req.method === 'GET' || req.path === '/activity') return next();

  res.on('finish', () => {
    if (res.statusCode >= 400) return;
    const match = MUTATION_FEATURES.find(([pattern]) => pattern.test(req.path));
    if (!match) return;

    const [, area, action] = match;
    // Income is its own feature: it is the thing most likely to go unused.
    const isIncome = area === 'everyday' && req.body?.direction === 'in';
    record({
      area,
      action: isIncome ? 'income' : action,
      detail: `${req.method} ${req.path}`,
    });
  });

  return next();
}

/**
 * Builds the Express app. Used both by the standalone server (`server.js`)
 * and by the Electron main process, which hosts it in-process.
 */
export function createApp({ distPath = resolve(here, '../../frontend/dist') } = {}) {
  const app = express();

  app.use(cors());
  app.use(express.json({ limit: '5mb' }));
  app.use(express.text({ type: 'text/csv', limit: '5mb' }));

  app.get('/api/health', (_req, res) => res.json({ ok: true }));
  app.use('/api/auth', authRouter);
  // Everything past here needs an unlocked session once a PIN has been set.
  app.use('/api', requireUnlocked, recordMutations, router);

  // Serve the built frontend when it exists, so the app is self-contained.
  if (distPath && existsSync(distPath)) {
    app.use(express.static(distPath));
    app.get(/^(?!\/api).*/, (_req, res) => res.sendFile(resolve(distPath, 'index.html')));
  }

  app.use((err, _req, res, _next) => {
    if (err instanceof ValidationError) {
      return res.status(400).json({ error: err.message, errors: err.errors });
    }
    if (err?.type === 'entity.parse.failed') {
      return res.status(400).json({ error: 'Malformed JSON body' });
    }
    console.error(err);
    return res.status(500).json({ error: 'Internal server error' });
  });

  return app;
}

/** Listens on an ephemeral port bound to loopback; resolves with the live server. */
export function startServer({ port = 0, host = '127.0.0.1', distPath } = {}) {
  const app = createApp({ distPath });
  return new Promise((resolvePromise, reject) => {
    const server = app.listen(port, host, () => resolvePromise(server));
    server.on('error', reject);
  });
}
