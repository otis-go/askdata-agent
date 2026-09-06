import { RSC_FORM_STATE_GLOBAL } from "./app-browser-hydration.js";
import { ReactFormState } from "react-dom/client";

//#region src/server/app-browser-stream.d.ts
type NavigationSnapshot = {
  pathname: string;
  searchParams: [string, string][];
};
type LegacyRscEmbedData = {
  rsc: string[];
  params?: Record<string, string | string[]>;
  nav?: NavigationSnapshot;
};
type VinextBrowserGlobals = {
  __VINEXT_RSC__?: LegacyRscEmbedData;
  __VINEXT_RSC_CHUNKS__?: string[];
  __VINEXT_RSC_DONE__?: boolean;
  [RSC_FORM_STATE_GLOBAL]?: ReactFormState;
  __VINEXT_RSC_PARAMS__?: Record<string, string | string[]>;
  __VINEXT_RSC_NAV__?: NavigationSnapshot;
};
declare function getVinextBrowserGlobal(): typeof globalThis & VinextBrowserGlobals;
/**
 * Convert embedded text chunks back to a ReadableStream of Uint8Array chunks.
 */
declare function chunksToReadableStream(chunks: readonly string[]): ReadableStream<Uint8Array>;
/**
 * Create a ReadableStream from progressively-embedded RSC chunks.
 *
 * The server pushes chunks into `__VINEXT_RSC_CHUNKS__` via inline <script>
 * tags. We monkey-patch `push()` so new chunks stream to React immediately
 * instead of polling with setTimeout.
 */
declare function createProgressiveRscStream(): ReadableStream<Uint8Array>;
//#endregion
export { chunksToReadableStream, createProgressiveRscStream, getVinextBrowserGlobal };
//# sourceMappingURL=app-browser-stream.d.ts.map