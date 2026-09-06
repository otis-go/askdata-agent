//#region src/cloudflare/tpr.d.ts
/**
 * TPR: Traffic-aware Pre-Rendering
 *
 * Uses Cloudflare zone analytics to determine which pages actually get
 * traffic, and pre-renders only those during deploy. The pre-rendered
 * HTML is uploaded to KV in the same format ISR uses at runtime — no
 * runtime changes needed.
 *
 * Flow:
 *   1. Parse wrangler config to find custom domain and KV namespace
 *   2. Resolve the Cloudflare zone for the custom domain
 *   3. Query zone analytics (GraphQL) for top pages by request count
 *   4. Walk ranked list until coverage threshold is met
 *   5. Start the built production server locally
 *   6. Fetch each hot route to produce HTML
 *   7. Upload pre-rendered HTML to KV (same KVCacheEntry format ISR reads)
 *
 * TPR is an experimental feature enabled via --experimental-tpr. It
 * gracefully skips when no custom domain, no API token, no traffic data,
 * or no KV namespace is configured.
 */
type TPROptions = {
  /** Project root directory. */root: string; /** Traffic coverage percentage (0–100). Default: 90. */
  coverage: number; /** Hard cap on number of pages to pre-render. Default: 1000. */
  limit: number; /** Analytics lookback window in hours. Default: 24. */
  window: number;
};
type TPRResult = {
  /** Total unique page paths found in analytics. */totalPaths: number; /** Number of pages successfully pre-rendered and uploaded. */
  prerenderedCount: number; /** Actual traffic coverage achieved (percentage). */
  coverageAchieved: number; /** Wall-clock duration of the TPR step in milliseconds. */
  durationMs: number; /** If TPR was skipped, the reason. */
  skipped?: string;
};
type PrerenderResult = {
  html: string;
  status: number;
  headers: Record<string, string>;
};
type WranglerConfig = {
  accountId?: string;
  kvNamespaceId?: string;
  customDomain?: string;
};
/**
 * Parse wrangler config (JSONC or TOML) to extract the fields TPR needs:
 * account_id, VINEXT_CACHE KV namespace ID, and custom domain.
 */
declare function parseWranglerConfig(root: string): WranglerConfig | null;
/**
 * Generate zone lookup candidates from shortest (2-part) to longest.
 * Tries the most common case first (e.g., "example.com") and progressively
 * adds labels for multi-part TLDs (e.g., "co.uk" → "example.co.uk").
 *
 * "shop.example.com"    → ["example.com", "shop.example.com"]
 * "shop.example.co.uk"  → ["co.uk", "example.co.uk", "shop.example.co.uk"]
 * "example.com"         → ["example.com"]
 */
declare function domainCandidates(domain: string): string[];
/**
 * Build KV bulk API pairs from pre-rendered entries.
 *
 * Key format matches the runtime KVCacheHandler exactly:
 *   ENTRY_PREFIX + isrCacheKey("app", pathname, buildId) + ":html"
 *   → "cache:app:<buildId>:<pathname>:html"
 */
declare function buildTprKVPairs(entries: Map<string, PrerenderResult>, buildId: string | undefined, defaultRevalidateSeconds: number): Array<{
  key: string;
  value: string;
  expiration_ttl: number;
}>;
/**
 * Run the TPR pipeline: query traffic, select routes, pre-render, upload.
 *
 * Designed to be called between the build step and wrangler deploy in
 * the `vinext deploy` pipeline. Gracefully skips (never errors) when
 * the prerequisites aren't met.
 */
declare function runTPR(options: TPROptions): Promise<TPRResult>;
//#endregion
export { TPROptions, TPRResult, buildTprKVPairs, domainCandidates, parseWranglerConfig, runTPR };
//# sourceMappingURL=tpr.d.ts.map