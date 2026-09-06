import { NEXT_DATA } from "../shims/internal/utils.js";

//#region src/client/vinext-next-data.d.ts
type VinextLinkPrefetchRoute = {
  patternParts: string[];
  isDynamic: boolean;
};
type VinextNextData = {
  /** vinext-specific additions (not part of Next.js upstream). */__vinext?: {
    /** Absolute URL of the page module for dynamic import. */pageModuleUrl?: string; /** Absolute URL of the `_app` module for dynamic import. */
    appModuleUrl?: string;
  };
} & NEXT_DATA;
//#endregion
export { VinextLinkPrefetchRoute, VinextNextData };
//# sourceMappingURL=vinext-next-data.d.ts.map