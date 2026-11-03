import test from 'node:test';
import assert from 'node:assert/strict';
import { activateOrVerify, licenseHash } from '../logic.js';

const pepper = 'test-pepper-'.repeat(4);
const key = 'WA-' + 'A'.repeat(32);
const otherKey = 'WA-' + 'C'.repeat(32);
const machine = 'a'.repeat(64), other = 'b'.repeat(64);
function fixture() {
  let record = { schema_version: 1, licenses: Object.fromEntries([key, otherKey].map(card =>
    [licenseHash(card, pepper), { enabled: true, expires_at: null, device_id: null, label: card.slice(-2) }])) };
  const bindings = new Map();
  let tail = Promise.resolve();
  const deps = {
    readRecord: async () => structuredClone(record),
    writeRecord: async value => { record = structuredClone(value); },
    readBinding: async digest => bindings.get(digest) || null,
    createBinding: async (digest, value) => {
      if (bindings.has(digest)) throw Object.assign(new Error(), { code: 'already_exists' });
      bindings.set(digest, structuredClone(value));
    },
    withLock: async action => {
      const previous = tail; let release;
      tail = new Promise(resolve => { release = resolve; });
      await previous;
      try { return await action(); } finally { release(); }
    },
    record: () => record, bindings
  };
  return deps;
}
const call = (deps, device_id = machine, license_key = key) => activateOrVerify({ license_key, device_id }, deps, pepper);

test('first activation binds automatically and updates JSONBin status', async () => {
  const deps = fixture();
  assert.equal((await call(deps)).activation, 'activated');
  const entry = deps.record().licenses[licenseHash(key, pepper)];
  assert.equal(entry.device_id, machine);
  assert.equal(entry.status, 'active');
  assert.ok(entry.activated_at);
  assert.equal((await call(deps)).activation, 'verified');
});
test('a second machine is rejected without changing the original binding', async () => {
  const deps = fixture(); await call(deps);
  await assert.rejects(call(deps, other), { code: 'bound_to_other_device' });
  assert.equal(deps.record().licenses[licenseHash(key, pepper)].device_id, machine);
});
test('two simultaneous devices activating one card have exactly one winner', async () => {
  const deps = fixture();
  const result = await Promise.allSettled([call(deps), call(deps, other)]);
  assert.equal(result.filter(r => r.status === 'fulfilled').length, 1);
  assert.equal(result.find(r => r.status === 'rejected').reason.code, 'bound_to_other_device');
});
test('concurrent different cards preserve both JSONBin updates', async () => {
  const deps = fixture();
  await Promise.all([call(deps), call(deps, other, otherKey)]);
  assert.equal(deps.record().licenses[licenseHash(key, pepper)].device_id, machine);
  assert.equal(deps.record().licenses[licenseHash(otherKey, pepper)].device_id, other);
});
test('a failed JSONBin write can be retried by the same device, never stolen', async () => {
  const deps = fixture(), write = deps.writeRecord;
  deps.writeRecord = async () => { throw new Error('storage offline'); };
  await assert.rejects(call(deps));
  await assert.rejects(call(deps, other), { code: 'bound_to_other_device' });
  deps.writeRecord = write;
  assert.equal((await call(deps)).ok, true);
});
test('disabled or expired cards cannot create a binding', async () => {
  for (const fields of [{ enabled: false }, { expires_at: '2020-01-01T00:00:00Z' }]) {
    const deps = fixture(); Object.assign(deps.record().licenses[licenseHash(key, pepper)], fields);
    await assert.rejects(call(deps)); assert.equal(deps.bindings.size, 0);
  }
});
