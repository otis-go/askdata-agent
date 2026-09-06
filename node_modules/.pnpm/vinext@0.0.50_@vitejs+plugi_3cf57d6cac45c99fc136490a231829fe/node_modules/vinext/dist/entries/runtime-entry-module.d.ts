//#region src/entries/runtime-entry-module.d.ts
/**
 * Convert Windows-style backslash path separators to forward slashes.
 *
 * Generated entry modules embed absolute filesystem paths inside `import`
 * statements. On Windows the OS-native paths use `\` which is invalid in JS
 * module specifiers, so every entry generator normalizes paths through this
 * helper before stringifying them into the emitted code.
 */
declare function normalizePathSeparators(p: string): string;
/**
 * Resolve a sibling module path relative to a caller's `import.meta.url`,
 * returning a forward-slash path safe for embedding in generated code.
 *
 * This is the single place that owns the
 * `fileURLToPath(new URL(rel, base))` + path-separator normalization idiom so
 * callers don't duplicate it.
 *
 * @param rel  - Relative path to the target module (e.g. `"../server/foo.js"`)
 * @param base - The caller's `import.meta.url`
 */
declare function resolveEntryPath(rel: string, base: string): string;
/**
 * Resolve a real runtime module for a virtual entry generator.
 *
 * During local development we want to point at source files (for example `.ts`),
 * while packed builds only contain emitted `.js` files in `dist/`. Probe the
 * common source/build extensions and fall back to the `.js` path that exists in
 * published packages.
 */
declare function resolveRuntimeEntryModule(name: string): string;
//#endregion
export { normalizePathSeparators, resolveEntryPath, resolveRuntimeEntryModule };
//# sourceMappingURL=runtime-entry-module.d.ts.map