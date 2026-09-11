import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { fetchJsonWithTimeout } from '../src/http.ts';

const realFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = realFetch; });

test('aborts a stalled connection and returns control to the viewer', async () => {
  let signal: AbortSignal | null | undefined;
  globalThis.fetch = (_input, init) => new Promise((_resolve, reject) => {
    signal = init?.signal;
    signal?.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
  });
  assert.equal(await fetchJsonWithTimeout('/cache.json', 'no-cache', 5), null);
  assert.equal(signal?.aborted, true);
});

test('timeout also covers a stalled JSON body after headers arrive', async () => {
  let signal: AbortSignal | null | undefined;
  globalThis.fetch = async (_input, init) => {
    signal = init?.signal;
    return new Response(new ReadableStream({
      start(controller) {
        signal?.addEventListener('abort', () => controller.error(new Error('aborted')), { once: true });
      },
    }));
  };
  assert.equal(await fetchJsonWithTimeout('/cache.json', 'no-cache', 5), null);
  assert.equal(signal?.aborted, true);
});

test('reads valid JSON and handles invalid JSON and HTTP failures', async () => {
  globalThis.fetch = async () => new Response('{"date":"2026-09-10"}');
  assert.deepEqual(await fetchJsonWithTimeout('/cache.json'), { date: '2026-09-10' });
  globalThis.fetch = async () => new Response('<html>offline</html>');
  assert.equal(await fetchJsonWithTimeout('/cache.json'), null);
  globalThis.fetch = async () => new Response('{}', { status: 503 });
  assert.equal(await fetchJsonWithTimeout('/cache.json'), null);
});
