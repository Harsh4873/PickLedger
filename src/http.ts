/** Bound both the connection and JSON body read so a stalled feed can recover. */
export async function fetchJsonWithTimeout<T>(
  url: string, cache: RequestCache = 'no-store', timeoutMs = 15_000,
): Promise<T | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { cache, signal: controller.signal });
    return response.ok ? await response.json() as T : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}
