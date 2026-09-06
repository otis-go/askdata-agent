//#region src/shims/font-local.d.ts
/**
 * next/font/local shim
 *
 * Provides a runtime-compatible shim for Next.js local fonts.
 * Generates @font-face CSS declarations and returns an object
 * with className, style, and variable properties.
 *
 * Supports both client-side injection and SSR collection,
 * matching the patterns used by the Google font shim.
 *
 * Usage:
 *   import localFont from 'next/font/local';
 *   const myFont = localFont({ src: './my-font.woff2' });
 *   // myFont.className -> unique CSS class
 *   // myFont.style -> { fontFamily: "'__local_font_0', sans-serif" }
 *   // myFont.variable -> generated class name (e.g. "__variable_local_0")
 */
type LocalFontSrc = {
  path: string;
  weight?: string;
  style?: string;
};
type LocalFontOptions = {
  src: string | LocalFontSrc | LocalFontSrc[];
  display?: string;
  weight?: string;
  style?: string;
  fallback?: string[];
  preload?: boolean;
  variable?: string;
  adjustFontFallback?: boolean | string;
  declarations?: Array<{
    prop: string;
    value: string;
  }>;
};
type FontResult = {
  className: string;
  style: {
    fontFamily: string;
  };
  variable?: string;
};
/**
 * Get collected SSR font styles (used by the renderer).
 * Note: We don't clear the arrays because fonts are loaded at module import
 * time and need to persist across all requests in the Workers environment.
 */
declare function getSSRFontStyles(): string[];
/**
 * Get collected SSR font preload data (used by the renderer).
 * Returns an array of { href, type } objects for emitting
 * <link rel="preload" as="font" ...> tags.
 */
declare function getSSRFontPreloads(): Array<{
  href: string;
  type: string;
}>;
declare function localFont(options: LocalFontOptions): FontResult;
//#endregion
export { localFont as default, getSSRFontPreloads, getSSRFontStyles };
//# sourceMappingURL=font-local.d.ts.map