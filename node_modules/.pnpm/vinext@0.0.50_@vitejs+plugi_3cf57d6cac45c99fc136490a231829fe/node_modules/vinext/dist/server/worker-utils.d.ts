//#region src/server/worker-utils.d.ts
declare function mergeHeaders(response: Response, extraHeaders: Record<string, string | string[]>, statusOverride?: number): Response;
declare function resolveStaticAssetSignal(signalResponse: Response, options: {
  fetchAsset(path: string): Promise<Response>;
}): Promise<Response | null>;
//#endregion
export { mergeHeaders, resolveStaticAssetSignal };
//# sourceMappingURL=worker-utils.d.ts.map