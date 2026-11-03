import { createHmac } from 'node:crypto';

export class LicenseError extends Error {
  constructor(code, status = 403) { super(code); this.code = code; this.status = status; }
}

export const licenseHash = (card, pepper) => createHmac('sha256', pepper).update(card, 'ascii').digest('hex');

export function checkRecord(record, digest, now) {
  if (record?.schema_version !== 1 || !record.licenses || typeof record.licenses !== 'object')
    throw new LicenseError('storage_unavailable', 503);
  const card = record.licenses[digest];
  if (!card) throw new LicenseError('invalid_card');
  if (card.enabled !== true) throw new LicenseError('disabled');
  if (card.expires_at !== null && card.expires_at !== undefined) {
    const deadline = Date.parse(card.expires_at);
    if (!Number.isFinite(deadline) || deadline <= now) throw new LicenseError('expired');
  }
  return card;
}

export async function activateOrVerify(payload, deps, pepper, now = Date.now()) {
  const { license_key: key, device_id: machine } = payload || {};
  if (typeof key !== 'string' || !/^WA-[A-F0-9]{32}$/.test(key) ||
      typeof machine !== 'string' || !/^[a-f0-9]{64}$/.test(machine))
    throw new LicenseError('invalid_card');
  if (typeof pepper !== 'string' || pepper.length < 32) throw new LicenseError('storage_unavailable', 503);
  const digest = licenseHash(key, pepper);
  const record = await deps.readRecord();
  const card = checkRecord(record, digest, now);
  let binding = await deps.readBinding(digest);
  let activated = false;
  if (!binding) {
    // Honor previously prebound cards when migrating the service.
    if (card.device_id != null && card.device_id !== machine) throw new LicenseError('bound_to_other_device');
    const candidate = { device_id: machine, activated_at: card.activated_at || new Date(now).toISOString() };
    try {
      // This must be an atomic create-if-absent, never an overwrite.
      await deps.createBinding(digest, candidate);
      binding = candidate;
      activated = true;
    } catch (error) {
      if (error.code !== 'already_exists') throw error;
      binding = await deps.readBinding(digest);
    }
  }
  if (!binding || !/^[a-f0-9]{64}$/.test(binding.device_id || '')) throw new LicenseError('storage_unavailable', 503);
  if (binding.device_id !== machine) throw new LicenseError('bound_to_other_device');
  if (card.device_id !== machine || card.status !== 'active' || card.activated_at !== binding.activated_at) {
    await deps.withLock(async () => {
      // Reload while locked: don't overwrite another card's activation or an admin edit.
      const latest = await deps.readRecord();
      const entry = checkRecord(latest, digest, Date.now());
      if (entry.device_id === machine && entry.status === 'active' && entry.activated_at === binding.activated_at) return;
      latest.licenses[digest] = { ...entry, device_id: machine, status: 'active', activated_at: binding.activated_at };
      await deps.writeRecord(latest);
    });
  }
  return { ok: true, device_id: machine, activation: activated ? 'activated' : 'verified', recheck_after: 45 };
}
