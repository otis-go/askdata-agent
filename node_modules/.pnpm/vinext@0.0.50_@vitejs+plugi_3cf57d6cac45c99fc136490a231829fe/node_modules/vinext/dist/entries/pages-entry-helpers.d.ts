import { createValidFileMatcher } from "../routing/file-matcher.js";

//#region src/entries/pages-entry-helpers.d.ts
/**
 * Find a file with any of the valid extensions in the given directory.
 * Returns the first matching absolute path, or null if not found.
 */
declare function findFileWithExts(dir: string, name: string, matcher: ReturnType<typeof createValidFileMatcher>): string | null;
//#endregion
export { findFileWithExts };
//# sourceMappingURL=pages-entry-helpers.d.ts.map