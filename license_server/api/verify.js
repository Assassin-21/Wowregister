import { randomUUID } from 'node:crypto';
import { get, put, del } from '@vercel/blob';
import { activateOrVerify, LicenseError } from '../logic.js';

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function readPrivate(path) {
  const result = await get(path, { access: 'private', useCache: false });
  if (!result) return null;
  if (result.statusCode !== 200) throw new LicenseError('storage_unavailable', 503);
  return { value: await new Response(result.stream).json(), etag: result.blob.etag };
}

async function writePrivate(path, value, options = {}) {
  return put(path, JSON.stringify(value), { access: 'private', addRandomSuffix: false,
    allowOverwrite: false, contentType: 'application/json', ...options });
}

async function withLock(action) {
  const path = 'locks/jsonbin-write.json';
  const deadline = Date.now() + 8000;
  let etag;
  while (Date.now() < deadline) {
    const current = await readPrivate(path);
    const lease = { owner: randomUUID(), expires_at: Date.now() + 75000 };
    try {
      if (current && current.value.expires_at > Date.now()) { await sleep(130); continue; }
      const result = await writePrivate(path, lease, current ? { allowOverwrite: true, ifMatch: current.etag } : {});
      etag = result.etag;
      break;
    } catch (error) {
      const observed = await readPrivate(path);
      if (observed?.value.owner === lease.owner) { etag = observed.etag; break; }
      if (!observed) throw error;
      await sleep(100);
    }
  }
  if (!etag) throw new LicenseError('activation_busy', 503);
  try { return await action(); }
  finally {
    try { await del(path, { ifMatch: etag }); }
    catch { console.warn(JSON.stringify({ event: 'binding_lock_release_deferred' })); }
  }
}

async function jsonbin(method = 'GET', record) {
  const bin = (process.env.JSONBIN_BIN_ID || '').trim();
  const master = (process.env.JSONBIN_MASTER_KEY || '').trim();
  const access = (process.env.JSONBIN_ACCESS_KEY || '').trim();
  if (!/^[a-f0-9]{24}$/i.test(bin) || !(master || access)) throw new LicenseError('storage_unavailable', 503);
  const response = await fetch(`https://api.jsonbin.io/v3/b/${bin}${method === 'GET' ? '/latest' : ''}`, {
    method, redirect: 'error', signal: AbortSignal.timeout(10000),
    headers: { 'User-Agent': 'Wowregister-License/0.4', Accept: 'application/json',
      'Content-Type': 'application/json', 'X-Bin-Meta': 'false', 'X-Bin-Versioning': 'false',
      ...(master ? { 'X-Master-Key': master } : { 'X-Access-Key': access }) },
    ...(record ? { body: JSON.stringify(record) } : {})
  });
  if (!response.ok) {
    const body = await response.text();
    let reason;
    try { reason = JSON.parse(body).message; } catch { reason = /1010/.test(body) ? 'cloudflare_1010' : 'non_json_response'; }
    console.error(JSON.stringify({ event: 'jsonbin_error', method, status: response.status,
      reason: typeof reason === 'string' ? reason.replaceAll(master || '\u0000', '[redacted]').replaceAll(access || '\u0000', '[redacted]').slice(0, 300) : 'unspecified' }));
    throw new LicenseError('storage_unavailable', 503);
  }
  return response.json();
}

const deps = {
  readRecord: () => jsonbin(), writeRecord: record => jsonbin('PUT', record), withLock,
  readBinding: async digest => (await readPrivate(`bindings/${digest}.json`))?.value || null,
  createBinding: async (digest, value) => {
    try { await writePrivate(`bindings/${digest}.json`, value); }
    catch (error) {
      if (await readPrivate(`bindings/${digest}.json`))
        throw Object.assign(new Error('already_exists'), { code: 'already_exists' });
      throw error;
    }
  }
};

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  if (req.method === 'GET') return res.status(200).json({ service: 'wowregister-license', version: '0.4.0', activation: 'automatic', status: 'online' });
  if (req.method !== 'POST') return res.status(405).json({ ok: false, code: 'invalid_request' });
  try {
    let payload = req.body;
    if (payload == null) {
      let raw = '';
      for await (const chunk of req) {
        raw += chunk;
        if (raw.length > 2048) throw new LicenseError('invalid_request', 400);
      }
      payload = JSON.parse(raw);
    } else if (typeof payload === 'string' || Buffer.isBuffer(payload)) payload = JSON.parse(payload.toString());
    return res.status(200).json(await activateOrVerify(payload, deps, process.env.LICENSE_PEPPER));
  } catch (error) {
    const known = error instanceof LicenseError;
    const code = known ? error.code : 'temporarily_unavailable';
    console.error(JSON.stringify({ event: 'license_response_error', code, name: error.name }));
    return res.status(known ? error.status : 503).json({ ok: false, code });
  }
}
