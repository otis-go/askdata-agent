//#region src/server/app-browser-action-result.d.ts
type AppBrowserServerActionResult<TRoot> = {
  root?: TRoot;
  returnValue?: {
    ok: boolean;
    data: unknown;
  };
};
/**
 * Structural discriminator: matches on `"returnValue"` or `"root"` keys.
 * This is safe because {@link AppWireElements} keys are prefixed (`route:`,
 * `slot:`, `__route`, etc.) and will never collide with these property names.
 * If the wire format ever adds a `"root"` key, this guard must be updated.
 */
declare function isServerActionResult<TRoot>(value: unknown): value is AppBrowserServerActionResult<TRoot>;
declare function shouldClearClientNavigationCachesForServerActionResult<TRoot>(result: AppBrowserServerActionResult<TRoot> | TRoot): boolean;
//#endregion
export { AppBrowserServerActionResult, isServerActionResult, shouldClearClientNavigationCachesForServerActionResult };
//# sourceMappingURL=app-browser-action-result.d.ts.map