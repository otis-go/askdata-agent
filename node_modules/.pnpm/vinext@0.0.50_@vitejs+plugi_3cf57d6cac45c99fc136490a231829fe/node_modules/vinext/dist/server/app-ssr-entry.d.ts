import { NavigationContext } from "../shims/navigation.js";
import { ReactFormState } from "react-dom/client";

//#region src/server/app-ssr-entry.d.ts
type FontPreload = {
  href: string;
  type: string;
};
type FontData = {
  links?: string[];
  styles?: string[];
  preloads?: FontPreload[];
};
declare function handleSsr(rscStream: ReadableStream<Uint8Array>, navContext: NavigationContext | null, fontData?: FontData, options?: {
  scriptNonce?: string;
  /** Pre-split side stream for embed+capture fusion. When provided,
   *  rscStream is fed directly to createFromReadableStream (no internal tee).
   *  The embed transform accumulates raw bytes. */
  sideStream?: ReadableStream<Uint8Array>; /** Out-parameter: filled with accumulated raw RSC bytes when sideStream is consumed. */
  capturedRscDataRef?: {
    value: Promise<ArrayBuffer> | null;
  };
  formState?: ReactFormState | null;
  /** When true, wait for the full React tree (including Suspense boundaries)
   *  to resolve before returning the HTML stream. Used for static prerender
   *  and ISR cache writes to avoid caching fallback content. */
  waitForAllReady?: boolean;
}): Promise<ReadableStream<Uint8Array>>;
declare const _default: {
  fetch(request: Request): Promise<Response>;
};
//#endregion
export { FontData, FontPreload, _default as default, handleSsr };
//# sourceMappingURL=app-ssr-entry.d.ts.map