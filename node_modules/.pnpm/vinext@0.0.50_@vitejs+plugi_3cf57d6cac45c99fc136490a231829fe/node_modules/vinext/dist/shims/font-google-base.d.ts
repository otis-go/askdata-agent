//#region src/shims/font-google-base.d.ts
type FontOptions = {
  weight?: string | string[];
  style?: string | string[];
  subsets?: string[];
  display?: string;
  preload?: boolean;
  fallback?: string[];
  adjustFontFallback?: boolean | string;
  variable?: string;
  axes?: string[];
};
type FontResult = {
  className: string;
  style: {
    fontFamily: string;
  };
  variable?: string;
};
type FontLoaderOptions = FontOptions & {
  _selfHostedCSS?: string;
};
/**
 * Build a Google Fonts CSS URL.
 *
 * In production this code path is dead. The build plugin
 * (`vinext:google-fonts` in `src/plugins/fonts.ts`) statically resolves
 * each font call's axis values against the bundled metadata, fetches the
 * Google Fonts CSS, and injects the resulting CSS as `_selfHostedCSS` so
 * the runtime never queries Google. The shim only reaches this builder
 * when the plugin's static parser bails (dynamic options, eval-only
 * shapes), which is dev-only.
 *
 * The dev fallback intentionally has no metadata: shipping the 388 KB
 * `font-data.json` to the Worker bundle would dwarf the rest of the shim,
 * and the production path already has the metadata-aware variant. The
 * tradeoff is that the dev fallback cannot resolve a variable font's
 * actual `wght` axis range. It emits no axis segment when no `weight` is
 * given, which makes Google return the default static face (200) instead
 * of the broken `:wght@100..900` URL that issue #885 reports.
 */
declare function buildGoogleFontsUrl(family: string, options: FontOptions): string;
/**
 * Get collected SSR font class styles (used by the renderer).
 * Note: We don't clear the arrays because fonts are loaded at module import
 * time and need to persist across all requests in the Workers environment.
 */
declare function getSSRFontStyles(): string[];
/**
 * Get collected SSR font URLs (used by the renderer).
 * Note: We don't clear the arrays because fonts are loaded at module import
 * time and need to persist across all requests in the Workers environment.
 */
declare function getSSRFontLinks(): string[];
/**
 * Get collected SSR font preload data (used by the renderer).
 * Returns an array of { href, type } objects for emitting
 * <link rel="preload" as="font" ...> tags.
 */
declare function getSSRFontPreloads(): Array<{
  href: string;
  type: string;
}>;
type FontLoader = (options?: FontLoaderOptions) => FontResult;
declare function createFontLoader(family: string): FontLoader;
declare const googleFonts: Record<string, FontLoader>;
//#endregion
export { FontLoader, FontOptions, FontResult, buildGoogleFontsUrl, createFontLoader, googleFonts as default, getSSRFontLinks, getSSRFontPreloads, getSSRFontStyles };
//# sourceMappingURL=font-google-base.d.ts.map