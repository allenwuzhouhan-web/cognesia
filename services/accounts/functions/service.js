import {createHash, randomBytes, timingSafeEqual} from 'node:crypto';

export const KEY_DAYS = 90;
export const KEY_PATTERN = /^cgnk_([a-f0-9]{32})\.([A-Za-z0-9_-]{43})$/;
export const digest = value => createHash('sha256').update(value).digest('hex');
export class AccountError extends Error {
  constructor(message, status = 400) { super(message); this.status = status; }
}

export function verifiedUser(user) {
  return Boolean(user && !user.disabled &&
    ((user.email && user.emailVerified) ||
      (user.phoneNumber && user.providerData?.some(p => p.providerId === 'phone'))));
}

export function identity(uid) {
  const id = digest('cognesia-firebase-v1:' + uid);
  return {customerId: 'u_' + id, workspaceId: 'local_' + id};
}

export function newKey(uid, now) {
  const id = randomBytes(16).toString('hex');
  const secret = `cgnk_${id}.${randomBytes(32).toString('base64url')}`;
  const {customerId, workspaceId} = identity(uid);
  const record = {uid, customerId, workspaceId, verifier: digest(secret),
    created: now, expires: now + KEY_DAYS * 86400_000, revoked: null};
  return {id, secret, record};
}

export function keySummary(id, key, now) {
  return {key_id: id, created_at: new Date(key.created).toISOString(),
    expires_at: new Date(key.expires).toISOString(),
    status: key.revoked !== null ? 'revoked' : key.expires <= now ? 'expired' : 'active'};
}

export class AccountService {
  constructor(db, auth, {clock = Date.now} = {}) { this.db = db; this.auth = auth; this.clock = clock; }
  accountRef(uid) { return this.db.collection('accounts').doc(identity(uid).customerId); }
  keyRef(id) { return this.db.collection('accessKeys').doc(id); }

  async authenticate(token, {recent = false} = {}) {
    let claims, user;
    try {
      claims = await this.auth.verifyIdToken(token, true);
      user = await this.auth.getUser(claims.uid);
    } catch { throw new AccountError('Sign in again to continue.', 401); }
    if (!verifiedUser(user)) throw new AccountError('Verify your email address or phone number first.', 403);
    if (recent && (!Number.isFinite(claims.auth_time) || this.clock() / 1000 - claims.auth_time > 600)) {
      throw new AccountError('Sign out and sign in again before changing your key.', 401);
    }
    return user;
  }

  async state(user) {
    const row = await this.accountRef(user.uid).get();
    const value = row.data();
    let key = null;
    if (value?.keyId) {
      const stored = await this.keyRef(value.keyId).get();
      if (stored.exists) key = keySummary(value.keyId, stored.data(), this.clock());
    }
    return {authenticated: true, enrolled: row.exists,
      contact: user.emailVerified ? user.email : user.phoneNumber,
      key, access: 'local_app', billing: false};
  }

  async issue(user, {enroll = false} = {}) {
    const now = this.clock();
    const candidate = newKey(user.uid, now);
    const accountRef = this.accountRef(user.uid);
    const created = await this.db.runTransaction(async tx => {
      const row = await tx.get(accountRef), account = row.data();
      if (account?.disabled) throw new AccountError('This account is unavailable.', 403);
      // Replayed enrollment never rotates an existing key or returns its secret.
      if (enroll && row.exists) return false;
      if (!enroll && !row.exists) throw new AccountError('Finish signup first.', 409);
      if (account && now - account.lastIssued < 30_000) throw new AccountError('Wait 30 seconds before replacing your key.', 429);
      const day = Math.floor(now / 86400_000);
      const issuedToday = account?.issueDay === day ? account.issuedToday : 0;
      if (issuedToday >= 5) throw new AccountError('Daily key limit reached. Try again tomorrow.', 429);
      if (account?.keyId) tx.update(this.keyRef(account.keyId), {revoked: now});
      tx.create(this.keyRef(candidate.id), candidate.record);
      tx.set(accountRef, {uid: user.uid, ...identity(user.uid), keyId: candidate.id,
        created: account?.created ?? now, lastIssued: now, issueDay: day, issuedToday: issuedToday + 1, disabled: false});
      return true;
    });
    const state = await this.state(user);
    if (created) state.issued_key = {api_key: candidate.secret, key_id: candidate.id,
      expires_at: new Date(candidate.record.expires).toISOString()};
    return state;
  }

  async revoke(user, id) {
    if (!/^[a-f0-9]{32}$/.test(id ?? '')) throw new AccountError('Invalid key identifier.');
    await this.db.runTransaction(async tx => {
      const key = await tx.get(this.keyRef(id));
      if (!key.exists || key.data().uid !== user.uid) throw new AccountError('Key not found.', 404);
      if (key.data().revoked === null) tx.update(this.keyRef(id), {revoked: this.clock()});
    });
    return this.state(user);
  }

  async access(secret) {
    const match = KEY_PATTERN.exec(secret ?? '');
    const denied = () => new AccountError('Personal key is invalid, expired or revoked.', 401);
    if (!match) throw denied();
    const row = await this.keyRef(match[1]).get(), key = row.data(), now = this.clock();
    if (!key || !/^[a-f0-9]{64}$/.test(key.verifier) ||
      !timingSafeEqual(Buffer.from(key.verifier, 'hex'), Buffer.from(digest(secret), 'hex')) ||
      key.revoked !== null || key.expires <= now) throw denied();
    const account = (await this.accountRef(key.uid).get()).data();
    if (!account || account.disabled || account.keyId !== match[1]) throw denied();
    let user;
    try { user = await this.auth.getUser(key.uid); }
    catch (error) {
      if (error.code === 'auth/user-not-found') throw denied();
      throw new AccountError('Access service is temporarily unavailable.', 503);
    }
    if (!verifiedUser(user)) throw denied();
    // A password reset or administrative token revocation also invalidates keys.
    const resetAt = Date.parse(user.tokensValidAfterTime || '');
    if (Number.isFinite(resetAt) && key.created < resetAt) throw denied();
    return {authenticated: true, authentication: 'customer_key', billing: false,
      customer: {id: key.customerId}, workspace: {id: key.workspaceId},
      scopes: ['read', 'run'], expires_at: new Date(key.expires).toISOString(),
      access: 'local_app', hosted_compute: false};
  }
}
