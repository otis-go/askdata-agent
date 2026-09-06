//#region src/shims/readonly-url-search-params.d.ts
/**
 * Read-only URLSearchParams wrapper matching Next.js runtime behavior.
 * Mutation methods remain present for instanceof/API compatibility but throw.
 */
declare class ReadonlyURLSearchParams extends URLSearchParams {
  append(_name: string, _value: string): never;
  delete(_name: string, _value?: string): never;
  set(_name: string, _value: string): never;
  sort(): never;
}
//#endregion
export { ReadonlyURLSearchParams };
//# sourceMappingURL=readonly-url-search-params.d.ts.map