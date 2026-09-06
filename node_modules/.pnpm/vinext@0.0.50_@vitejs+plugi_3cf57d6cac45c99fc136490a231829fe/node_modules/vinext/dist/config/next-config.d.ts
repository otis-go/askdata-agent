import { PHASE_PRODUCTION_BUILD } from "../shims/constants.js";

//#region src/config/next-config.d.ts
/**
 * Parse a body size limit value (string or number) into bytes.
 * Accepts Next.js-style strings like "1mb", "500kb", "10mb", bare number strings like "1048576" (bytes),
 * and numeric values. Supports b, kb, mb, gb, tb, pb units.
 * Returns the default 1MB if the value is not provided or invalid.
 * Throws if the parsed value is less than 1.
 */
declare function parseBodySizeLimit(value: string | number | undefined | null): number;
type HasCondition = {
  type: "header" | "cookie" | "query" | "host";
  key: string;
  value?: string;
};
type NextRedirect = {
  source: string;
  destination: string;
  permanent: boolean;
  has?: HasCondition[];
  missing?: HasCondition[];
};
type NextRewrite = {
  source: string;
  destination: string;
  has?: HasCondition[];
  missing?: HasCondition[];
};
type NextHeader = {
  source: string;
  has?: HasCondition[];
  missing?: HasCondition[];
  headers: Array<{
    key: string;
    value: string;
  }>;
};
type NextI18nConfig = {
  /** List of supported locales */locales: string[]; /** The default locale (used when no locale prefix is in the URL) */
  defaultLocale: string;
  /**
   * Whether to auto-detect locale from Accept-Language header.
   * Defaults to true in Next.js.
   */
  localeDetection?: boolean;
  /**
   * Domain-based routing. Each domain maps to a specific locale.
   */
  domains?: Array<{
    domain: string;
    defaultLocale: string;
    locales?: string[];
    http?: boolean;
  }>;
};
/**
 * MDX compilation options extracted from @next/mdx config.
 * These are passed through to @mdx-js/rollup so that custom
 * remark/rehype/recma plugins configured in next.config work with Vite.
 */
type MdxOptions = {
  remarkPlugins?: unknown[];
  rehypePlugins?: unknown[];
  recmaPlugins?: unknown[];
};
type NextConfig = {
  /** Additional env variables */env?: Record<string, string>; /** Base URL path prefix */
  basePath?: string; /** Whether to add trailing slashes */
  trailingSlash?: boolean; /** Internationalization routing config */
  i18n?: NextI18nConfig; /** URL redirect rules */
  redirects?: () => Promise<NextRedirect[]> | NextRedirect[]; /** URL rewrite rules */
  rewrites?: () => Promise<NextRewrite[] | {
    beforeFiles: NextRewrite[];
    afterFiles: NextRewrite[];
    fallback: NextRewrite[];
  }> | NextRewrite[] | {
    beforeFiles: NextRewrite[];
    afterFiles: NextRewrite[];
    fallback: NextRewrite[];
  }; /** Custom response headers */
  headers?: () => Promise<NextHeader[]> | NextHeader[]; /** Image optimization config */
  images?: {
    remotePatterns?: Array<{
      protocol?: string;
      hostname: string;
      port?: string;
      pathname?: string;
      search?: string;
    }>;
    domains?: string[];
    unoptimized?: boolean; /** Allowed device widths for image optimization. Defaults to Next.js defaults: [640, 750, 828, 1080, 1200, 1920, 2048, 3840] */
    deviceSizes?: number[]; /** Allowed image sizes for fixed-width images. Defaults to Next.js defaults: [16, 32, 48, 64, 96, 128, 256, 384] */
    imageSizes?: number[]; /** Allow SVG images through the image optimization endpoint. SVG can contain scripts, so only enable if you trust all image sources. */
    dangerouslyAllowSVG?: boolean; /** Allow image optimization for hostnames that resolve to private IP addresses. This is a security risk (SSRF) — only enable for private networks when you understand the risk. */
    dangerouslyAllowLocalIP?: boolean; /** Content-Disposition header for image responses. Defaults to "inline". */
    contentDispositionType?: "inline" | "attachment"; /** Content-Security-Policy header for image responses. Defaults to "script-src 'none'; frame-src 'none'; sandbox;" */
    contentSecurityPolicy?: string;
  }; /** Build output mode: 'export' for full static export, 'standalone' for single server */
  output?: "export" | "standalone"; /** File extensions treated as routable pages/routes (Next.js pageExtensions) */
  pageExtensions?: string[]; /** Extra origins allowed to access the dev server. */
  allowedDevOrigins?: string[]; /** Maximum age in seconds for stale ISR entries before blocking regeneration. */
  expireTime?: number;
  /**
   * Enable Cache Components (Next.js 16).
   * When true, enables the "use cache" directive for pages, components, and functions.
   * Replaces the removed experimental.ppr and experimental.dynamicIO flags.
   */
  cacheComponents?: boolean;
  /**
   * Enables source maps while generating static pages.
   * Helps with errors during the prerender phase in `vinext build`.
   * Defaults to `true`. Set to `false` to disable.
   */
  enablePrerenderSourceMaps?: boolean; /** Transpile packages (Vite handles this natively) */
  transpilePackages?: string[];
  /**
   * Packages that should be treated as server-external (not bundled by Vite).
   * Corresponds to Next.js `serverExternalPackages` (or the legacy
   * `experimental.serverComponentsExternalPackages`).
   */
  serverExternalPackages?: string[]; /** Webpack config (ignored — we use Vite) */
  webpack?: unknown;
  /**
   * Path to a custom cache handler module (e.g., KV, Redis, DynamoDB).
   * Accepts relative paths, absolute paths, or file:// URLs from import.meta.resolve().
   * When "type": "module" is set in package.json, use import.meta.resolve() instead of
   * require.resolve() to get a valid path.
   */
  cacheHandler?: string;
  /**
   * Maximum memory size (bytes) for the default in-memory cache handler.
   * Set to 0 to disable in-memory caching entirely.
   */
  cacheMaxMemorySize?: number;
  /**
   * Custom build ID generator. If provided, called once at build/dev start.
   * Must return a non-empty string, or null to use the default random ID.
   */
  generateBuildId?: () => string | null | Promise<string | null>; /** Identifier for deployment-aware cache keys and version skew protection. */
  deploymentId?: string; /** Any other options */
  [key: string]: unknown;
};
type NextConfigFactory = (phase: string, opts: {
  defaultConfig: NextConfig;
}) => NextConfig | Promise<NextConfig>;
type NextConfigInput = NextConfig | NextConfigFactory;
/**
 * Resolved configuration with all async values awaited.
 */
type ResolvedNextConfig = {
  env: Record<string, string>;
  basePath: string;
  trailingSlash: boolean;
  output: "" | "export" | "standalone";
  pageExtensions: string[];
  cacheComponents: boolean;
  redirects: NextRedirect[];
  rewrites: {
    beforeFiles: NextRewrite[];
    afterFiles: NextRewrite[];
    fallback: NextRewrite[];
  };
  headers: NextHeader[];
  images: NextConfig["images"];
  i18n: NextI18nConfig | null; /** MDX remark/rehype/recma plugins extracted from @next/mdx config */
  mdx: MdxOptions | null; /** Explicit module aliases preserved from wrapped next.config plugins. */
  aliases: Record<string, string>; /** Extra allowed origins for dev server access (from allowedDevOrigins). */
  allowedDevOrigins: string[]; /** Extra allowed origins for server action CSRF validation (from experimental.serverActions.allowedOrigins). */
  serverActionsAllowedOrigins: string[]; /** Packages whose barrel imports should be optimized (from experimental.optimizePackageImports). */
  optimizePackageImports: string[]; /** Parsed body size limit for server actions in bytes (from experimental.serverActions.bodySizeLimit). Defaults to 1MB. */
  serverActionsBodySizeLimit: number; /** Route-level expire fallback in seconds for ISR entries with numeric revalidate. */
  expireTime: number;
  /**
   * Packages that should be treated as server-external (not bundled by Vite).
   * Sourced from `serverExternalPackages` or the legacy
   * `experimental.serverComponentsExternalPackages` in next.config.
   */
  serverExternalPackages: string[]; /** Enable sourcemaps for prerender error stack traces. Defaults to true. */
  enablePrerenderSourceMaps: boolean; /** Resolved build ID (from generateBuildId, or a random UUID if not provided). */
  buildId: string; /** Resolved deployment ID from next.config.js or NEXT_DEPLOYMENT_ID. */
  deploymentId: string | undefined;
  /**
   * Path to a custom cache handler module. file:// URLs are resolved to
   * filesystem paths via fileURLToPath() during config resolution.
   */
  cacheHandler: string | undefined;
  /**
   * Maximum memory size (bytes) for the default in-memory cache handler.
   * Set to 0 to disable in-memory caching entirely.
   */
  cacheMaxMemorySize: number | undefined;
  /**
   * Concatenated hash salt from `experimental.outputHashSalt` config option
   * and `NEXT_HASH_SALT` environment variable. Empty string when neither is set.
   * When non-empty, mix into content-addressed output filenames so hash values
   * change without modifying source — useful for cache-busting after CDN poisoning.
   */
  hashSalt: string;
};
declare function findNextConfigPath(root: string): string | null;
declare function resolveNextConfigInput(config: NextConfigInput, phase?: string): Promise<NextConfig>;
/**
 * Find and load the next.config file from the project root.
 * Returns null if no config file is found.
 *
 * Attempts Vite's module runner first so TS configs and extensionless local
 * imports (e.g. `import "./env"`) resolve consistently. If loading fails due
 * to CJS constructs (`require`, `module.exports`), falls back to `createRequire`
 * so common CJS plugin wrappers (nextra, @next/mdx, etc.) still work.
 */
declare function loadNextConfig(root: string, phase?: string): Promise<NextConfig | null>;
/**
 * Resolve a NextConfig into a fully-resolved ResolvedNextConfig.
 * Awaits async functions for redirects/rewrites/headers.
 */
declare function resolveNextConfig(config: NextConfig | null, root?: string): Promise<ResolvedNextConfig>;
/**
 * Extract MDX compilation options (remark/rehype/recma plugins) from
 * a Next.js config that uses @next/mdx.
 *
 * @next/mdx wraps the config with a webpack function that injects an MDX
 * loader rule. The remark/rehype plugins are captured in that closure.
 * We probe the webpack function with a mock config to extract them.
 */
declare function extractMdxOptions(config: NextConfig, root?: string): Promise<MdxOptions | null>;
/**
 * Detect next-intl in the project and auto-register the `next-intl/config`
 * alias if needed.
 *
 * next-intl's `createNextIntlPlugin()` crashes in vinext because it calls
 * `require('next/package.json')` to check the Next.js version. Instead,
 * vinext detects next-intl and registers the alias automatically.
 *
 * Note: `require.resolve('next-intl')` walks up to parent `node_modules`
 * directories via standard Node module resolution. In a monorepo, next-intl
 * installed at the workspace root will trigger detection even if not listed
 * in the project's own package.json. This is acceptable since a workspace-root
 * install implies the user wants it available.
 *
 * Mutates `resolved.aliases` and `resolved.env` in place.
 */
declare function detectNextIntlConfig(root: string, resolved: ResolvedNextConfig): void;
//#endregion
export { HasCondition, MdxOptions, NextConfig, NextConfigFactory, NextConfigInput, NextHeader, NextI18nConfig, NextRedirect, NextRewrite, PHASE_PRODUCTION_BUILD, ResolvedNextConfig, detectNextIntlConfig, extractMdxOptions, findNextConfigPath, loadNextConfig, parseBodySizeLimit, resolveNextConfig, resolveNextConfigInput };
//# sourceMappingURL=next-config.d.ts.map