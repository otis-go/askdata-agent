import { createValidFileMatcher } from "../routing/file-matcher.js";
import { ResolvedNextConfig } from "../config/next-config.js";

//#region src/entries/pages-client-entry.d.ts
declare function generateClientEntry(pagesDir: string, nextConfig: ResolvedNextConfig, fileMatcher: ReturnType<typeof createValidFileMatcher>): Promise<string>;
//#endregion
export { generateClientEntry };
//# sourceMappingURL=pages-client-entry.d.ts.map