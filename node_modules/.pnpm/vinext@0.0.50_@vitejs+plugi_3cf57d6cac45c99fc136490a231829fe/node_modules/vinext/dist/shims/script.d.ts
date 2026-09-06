import React from "react";

//#region src/shims/script.d.ts
type ScriptProps = {
  /** Script source URL */src?: string; /** Loading strategy. Default: "afterInteractive" */
  strategy?: "beforeInteractive" | "afterInteractive" | "lazyOnload" | "worker"; /** Unique identifier for the script */
  id?: string; /** Called when the script has loaded */
  onLoad?: (e: Event) => void; /** Called when the script is ready (after load, and on every re-render if already loaded) */
  onReady?: () => void; /** Called on script load error */
  onError?: (e: Event) => void; /** Inline script content */
  children?: React.ReactNode; /** Dangerous inner HTML */
  dangerouslySetInnerHTML?: {
    __html: string;
  }; /** Script type attribute */
  type?: string; /** Async attribute */
  async?: boolean; /** Defer attribute */
  defer?: boolean; /** Crossorigin attribute */
  crossOrigin?: string; /** Nonce for CSP */
  nonce?: string; /** Integrity hash */
  integrity?: string; /** Additional attributes */
  [key: string]: unknown;
};
/**
 * Load a script imperatively (outside of React).
 */
declare function handleClientScriptLoad(props: ScriptProps): void;
/**
 * Initialize multiple scripts at once (called during app bootstrap).
 */
declare function initScriptLoader(scripts: ScriptProps[]): void;
declare function Script(props: ScriptProps): React.ReactElement | null;
//#endregion
export { ScriptProps, Script as default, handleClientScriptLoad, initScriptLoader };
//# sourceMappingURL=script.d.ts.map