//#region src/server/rsc-stream-hints.d.ts
declare function normalizeReactFlightPreloadHints(stream: ReadableStream<Uint8Array>): ReadableStream<Uint8Array>;
type RscRawRenderer = (model: unknown, options?: unknown) => ReadableStream<Uint8Array>;
declare function createRscRenderer(render: RscRawRenderer): RscRawRenderer;
//#endregion
export { createRscRenderer, normalizeReactFlightPreloadHints };
//# sourceMappingURL=rsc-stream-hints.d.ts.map