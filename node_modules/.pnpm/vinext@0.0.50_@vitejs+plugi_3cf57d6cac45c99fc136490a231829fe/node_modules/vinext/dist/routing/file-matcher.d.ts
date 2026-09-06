//#region src/routing/file-matcher.d.ts
declare function normalizePageExtensions(pageExtensions?: readonly string[] | null): string[];
type ValidFileMatcher = {
  extensions: string[];
  dottedExtensions: string[];
  extensionRegex: RegExp;
  isPageFile(filePath: string): boolean;
  isAppRouterPage(filePath: string): boolean;
  isAppRouterRoute(filePath: string): boolean;
  isAppLayoutFile(filePath: string): boolean;
  isAppDefaultFile(filePath: string): boolean;
  stripExtension(filePath: string): string;
};
/**
 * Ported in spirit from Next.js createValidFileMatcher:
 * packages/next/src/server/lib/find-page-file.ts
 */
declare function createValidFileMatcher(pageExtensions?: readonly string[] | null): ValidFileMatcher;
/** Check if a file exists with any configured page extension. */
declare function findFileWithExtensions(basePath: string, matcher: ValidFileMatcher): boolean;
/**
 * Use function-form exclude for Node < 22.14 compatibility.
 */
declare function scanWithExtensions(stem: string, cwd: string, extensions: readonly string[], exclude?: (name: string) => boolean): AsyncGenerator<string>;
//#endregion
export { ValidFileMatcher, createValidFileMatcher, findFileWithExtensions, normalizePageExtensions, scanWithExtensions };
//# sourceMappingURL=file-matcher.d.ts.map