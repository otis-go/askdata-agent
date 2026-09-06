//#region src/plugins/strip-server-exports.d.ts
/**
 * Strip server-only data-fetching exports (getServerSideProps,
 * getStaticProps, getStaticPaths) from page modules for the client
 * bundle. Uses Vite's parseAst (Rollup/acorn) for correct handling
 * of all export patterns including function expressions, arrow
 * functions with TS return types, and re-exports.
 *
 * Modeled after Next.js's SWC `next-ssg-transform`.
 */
declare function stripServerExports(code: string): string | null;
//#endregion
export { stripServerExports };
//# sourceMappingURL=strip-server-exports.d.ts.map