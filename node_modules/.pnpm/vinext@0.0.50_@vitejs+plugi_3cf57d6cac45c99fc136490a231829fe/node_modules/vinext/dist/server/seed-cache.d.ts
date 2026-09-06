//#region src/server/seed-cache.d.ts
/**
 * Seed the memory cache from pre-rendered build output.
 *
 * Reads `vinext-prerender.json` and the corresponding HTML/RSC files from
 * `dist/server/prerendered-routes/`, then populates the active CacheHandler
 * so pre-rendered pages are served as cache HITs on the very first request
 * instead of triggering a full re-render.
 *
 * This is only useful for the MemoryCacheHandler (the default for Node.js
 * production). Persistent backends like KV already retain entries across
 * deploys and can be pre-populated via TPR or similar mechanisms.
 *
 * Consistency model:
 * - The manifest is authoritative for which routes were pre-rendered and their
 *   revalidation config. The HTML/RSC files on disk are the source of truth
 *   for content. Both are produced by the same build and are immutable after
 *   the build completes.
 * - Cache keys include the buildId, so entries from a previous build are never
 *   matched by a new server process (new build = new buildId = new keys).
 * - Seeded entries are indistinguishable from entries created by the ISR
 *   render path: same cache value shape, same revalidate duration tracking,
 *   same cache key construction. The serving path does not know or care
 *   whether an entry was seeded or rendered.
 *
 * Concurrency model:
 * - This function runs at startup before the HTTP server begins accepting
 *   requests, so there are no concurrent readers during seeding. All I/O is
 *   synchronous (readFileSync) which is appropriate for a startup-only path
 *   that runs once before the event loop serves traffic.
 */
/**
 * Read pre-rendered routes from disk and seed the active CacheHandler.
 *
 * Call this during production server startup, before any requests are served.
 * If the manifest doesn't exist (no prerender phase was run), this is a no-op.
 *
 * @param serverDir - Path to `dist/server/` (where vinext-prerender.json lives)
 * @returns The number of routes seeded (0 if no manifest or no renderable routes).
 */
declare function seedMemoryCacheFromPrerender(serverDir: string): Promise<number>;
//#endregion
export { seedMemoryCacheFromPrerender };
//# sourceMappingURL=seed-cache.d.ts.map