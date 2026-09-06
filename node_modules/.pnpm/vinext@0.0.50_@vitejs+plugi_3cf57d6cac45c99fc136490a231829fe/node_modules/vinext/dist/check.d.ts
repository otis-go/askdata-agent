//#region src/check.d.ts
/**
 * vinext check — compatibility scanner for Next.js apps
 *
 * Scans an existing Next.js app and produces a compatibility report
 * showing what will work, what needs changes, and an overall score.
 */
type Status = "supported" | "partial" | "unsupported";
type CheckItem = {
  name: string;
  status: Status;
  detail?: string;
  files?: string[];
};
type CheckResult = {
  imports: CheckItem[];
  config: CheckItem[];
  libraries: CheckItem[];
  conventions: CheckItem[];
  summary: {
    supported: number;
    partial: number;
    unsupported: number;
    total: number;
    score: number;
  };
};
/**
 * Scan source files for `import ... from 'next/...'` statements.
 */
declare function scanImports(root: string): CheckItem[];
/**
 * Analyze next.config.js/mjs/ts for supported and unsupported options.
 */
declare function analyzeConfig(root: string): CheckItem[];
/**
 * Check package.json dependencies for known libraries.
 */
declare function checkLibraries(root: string): CheckItem[];
/**
 * Check file conventions (pages, app directory, middleware, etc.)
 */
declare function checkConventions(root: string): CheckItem[];
/**
 * Run the full compatibility check.
 */
declare function runCheck(root: string): CheckResult;
/**
 * Format the check result as a colored terminal report.
 */
declare function formatReport(result: CheckResult, opts?: {
  calledFromInit?: boolean;
}): string;
//#endregion
export { CheckResult, analyzeConfig, checkConventions, checkLibraries, formatReport, runCheck, scanImports };
//# sourceMappingURL=check.d.ts.map