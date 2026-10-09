import express from 'express';
import {AccountError, AccountService, digest} from './service.js';

export function makeApp({db, auth, origin, phoneEnabled = false, googleEnabled = false, clock = Date.now}) {
  const app = express(), service = new AccountService(db, auth, {clock});
  app.disable('x-powered-by');
  app.use((req, res, next) => {
    res.set({'Cache-Control': 'no-store, max-age=0', 'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY'});
    next();
  });
  // Bounded per-instance limits complement Firebase Auth's delivery controls.
  // Provider quotas remain separate from this per-instance abuse limit.
  const requests = new Map();
  app.use((req, res, next) => {
    const now = clock(), bucket = Math.floor(now / 60_000);
    const id = digest(String(req.ip || '') + ':' + String(req.headers.authorization || '').slice(0, 4096));
    const entry = requests.get(id);
    if (requests.size >= 4096) for (const [key, item] of requests) if (item.bucket !== bucket) requests.delete(key);
    if ((!entry && requests.size >= 4096) || (entry?.bucket === bucket && entry.count >= 120)) {
      res.set('Retry-After', '60'); return next(new AccountError('Too many requests. Please wait one minute.', 429));
    }
    requests.set(id, {bucket, count: entry?.bucket === bucket ? entry.count + 1 : 1});
    next();
  });
  app.use(express.json({limit: '2kb', strict: true}));
  const bearer = req => {
    const value = req.headers.authorization || '';
    if (!/^Bearer [A-Za-z0-9_.-]{16,4096}$/.test(value)) throw new AccountError('Sign in to continue.', 401);
    return value.slice(7);
  };
  const sameOrigin = req => {
    if (!origin || req.headers.origin !== origin || req.headers['x-cognesia-account'] !== '1') {
      throw new AccountError('Use the Cognesia account website.', 403);
    }
    if (!req.is('application/json')) throw new AccountError('Expected JSON.', 415);
    if (Object.keys(req.query).length) throw new AccountError('Unexpected query parameters.');
  };
  app.get('/api/config', (req, res) => res.json({available: Boolean(origin), phone_enabled: phoneEnabled, google_enabled: googleEnabled}));
  app.get('/api/account', async (req, res) => res.json(await service.state(await service.authenticate(bearer(req)))));
  app.post('/api/:action', async (req, res) => {
    sameOrigin(req);
    const action = req.params.action;
    if (!['enroll', 'replace', 'revoke'].includes(action)) throw new AccountError('Not found.', 404);
    const fields = action === 'revoke' ? ['key_id'] : [];
    if (!req.body || Array.isArray(req.body) || JSON.stringify(Object.keys(req.body).sort()) !== JSON.stringify(fields)) {
      throw new AccountError('Invalid account request.');
    }
    const user = await service.authenticate(bearer(req), {recent: true});
    const result = action === 'revoke' ? await service.revoke(user, req.body.key_id)
      : await service.issue(user, {enroll: action === 'enroll'});
    res.status(result.issued_key ? 201 : 200).json(result);
  });
  app.get('/v1/access', async (req, res) => {
    if (Object.keys(req.query).length) throw new AccountError('Credentials belong in the Authorization header.');
    res.json(await service.access(bearer(req)));
  });
  app.use((req, res) => res.status(404).json({error: {message: 'Not found.'}}));
  app.use((error, req, res, next) => {
    const status = error instanceof AccountError ? error.status : error.type === 'entity.too.large' ? 413 : error.type === 'entity.parse.failed' ? 400 : 503;
    const message = error instanceof AccountError ? error.message : status === 503 ? 'Account service is temporarily unavailable.' : 'Invalid account request.';
    if (status === 429) res.set('Retry-After', '30');
    // Do not log request bodies, identity tokens, contact details or personal keys.
    if (status === 503) console.error('Account service failure', error.code || error.name || 'unknown');
    res.status(status).json({error: {message}});
  });
  return app;
}
