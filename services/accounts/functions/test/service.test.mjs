import test from 'node:test';
import assert from 'node:assert/strict';
import {verifiedUser, newKey, digest, KEY_PATTERN, identity} from '../service.js';

test('only a verified contact on an enabled provider account is accepted', () => {
  for (const user of [null, {}, {email:'reader@example.test'}, {email:'reader@example.test',emailVerified:false},
    {phoneNumber:'+15555550100',providerData:[]}, {email:'reader@example.test',emailVerified:true,disabled:true}]) {
    assert.equal(verifiedUser(user), false);
  }
  assert.equal(verifiedUser({email:'reader@example.test',emailVerified:true}), true);
  assert.equal(verifiedUser({phoneNumber:'+15555550100',providerData:[{providerId:'phone'}]}), true);
});

test('keys preserve the app contract without storing their secret', () => {
  const first=newKey('one-user', Date.now()), second=newKey('one-user', Date.now());
  assert.match(first.secret,KEY_PATTERN); assert.notEqual(first.secret,second.secret);
  assert.equal(first.record.verifier,digest(first.secret));
  assert.equal(JSON.stringify(first.record).includes(first.secret),false);
  assert.deepEqual(identity('one-user'),identity('one-user'));
  assert.notDeepEqual(identity('one-user'),identity('different-user'));
  assert.match(first.record.workspaceId,/^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/);
});
