//#region src/server/app-mounted-slots-header.d.ts
/**
 * Normalize the `x-vinext-mounted-slots` header for request handling and cache keying.
 *
 * The browser sends mounted slot ids as a space-separated list in the order slots were
 * rendered, which changes across navigations. This normalizes to a canonical form
 * (sorted, deduplicated) so equivalent slot sets map to the same RSC cache entry.
 *
 * Consumed by:
 *   - app-rsc-request-normalization (request lifecycle, reads incoming header)
 *   - app-elements (outgoing x-vinext-mounted-slots construction)
 *   - isr-cache (RSC cache key generation)
 */
declare function normalizeMountedSlotsHeader(raw: string | null | undefined): string | null;
//#endregion
export { normalizeMountedSlotsHeader };
//# sourceMappingURL=app-mounted-slots-header.d.ts.map