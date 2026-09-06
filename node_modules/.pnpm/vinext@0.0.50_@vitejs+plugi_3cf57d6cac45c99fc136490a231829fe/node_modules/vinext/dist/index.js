import { detectPackageManager } from "./utils/project.js";
import { normalizePathnameForRouteMatchStrict } from "./routing/utils.js";
import { createValidFileMatcher } from "./routing/file-matcher.js";
import { hasBasePath, removeTrailingSlash } from "./utils/base-path.js";
import { apiRouter, invalidateRouteCache, matchRoute, pagesRouter } from "./routing/pages-router.js";
import { INTERNAL_HEADERS, VINEXT_MW_CTX_HEADER, VINEXT_TIMING_HEADER } from "./server/headers.js";
import { buildRequestHeadersFromMiddlewareResponse } from "./server/middleware-request-headers.js";
import { normalizePath as normalizePath$1 } from "./server/normalize-path.js";
import { isExternalUrl, matchHeaders, matchRedirect, matchRewrite, proxyExternalRequest, requestContextFromRequest, sanitizeDestination } from "./config/config-matchers.js";
import { filterInternalHeaders, isOpenRedirectShaped } from "./server/request-pipeline.js";
import { findMiddlewareFile, runMiddleware } from "./server/middleware.js";
import { generateServerEntry } from "./entries/pages-server-entry.js";
import { generateClientEntry } from "./entries/pages-client-entry.js";
import { appRouter, invalidateAppRouteCache } from "./routing/app-router.js";
import { findInstrumentationClientFile, findInstrumentationFile, runInstrumentation } from "./server/instrumentation.js";
import { logRequest, now } from "./server/request-log.js";
import { createSSRHandler } from "./server/dev-server.js";
import { handleApiRoute } from "./server/api-handler.js";
import { installSocketErrorBackstop } from "./server/socket-error-backstop.js";
import { scanMetadataFiles } from "./server/metadata-routes.js";
import { shouldInvalidateAppRouteFile } from "./server/dev-route-files.js";
import { createDirectRunner } from "./server/dev-module-runner.js";
import { validateDevRequest } from "./server/dev-origin-check.js";
import { generateRscEntry } from "./entries/app-rsc-entry.js";
import { generateSsrEntry } from "./entries/app-ssr-entry.js";
import { generateBrowserEntry } from "./entries/app-browser-entry.js";
import { collectRouteClassificationManifest } from "./build/route-classification-manifest.js";
import { planRouteClassificationInjection } from "./build/route-classification-injector.js";
import { PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD } from "./shims/constants.js";
import { findNextConfigPath, loadNextConfig, resolveNextConfig, resolveNextConfigInput } from "./config/next-config.js";
import { precompressAssets } from "./build/precompress.js";
import { manifestFileWithBase, manifestFilesWithBase } from "./utils/manifest-paths.js";
import { asyncHooksStubPlugin } from "./plugins/async-hooks-stub.js";
import { clientReferenceDedupPlugin } from "./plugins/client-reference-dedup.js";
import { createRscClientReferenceLoadersPlugin } from "./plugins/rsc-client-reference-loaders.js";
import { createInstrumentationClientTransformPlugin } from "./plugins/instrumentation-client.js";
import { createOptimizeImportsPlugin } from "./plugins/optimize-imports.js";
import { createOgInlineFetchAssetsPlugin, ogAssetsPlugin } from "./plugins/og-assets.js";
import { SSR_EXTERNAL_REACT_ENTRIES, VINEXT_OPTIMIZE_DEPS_EXCLUDE, mergeOptimizeDepsExclude } from "./plugins/rsc-client-shim-excludes.js";
import { createServerExternalsManifestPlugin } from "./plugins/server-externals-manifest.js";
import { RESOLVED_VIRTUAL_GOOGLE_FONTS, VIRTUAL_GOOGLE_FONTS, createGoogleFontsPlugin, createLocalFontsPlugin, generateGoogleFontsVirtualModule, parseStaticObjectLiteral } from "./plugins/fonts.js";
import { computeLazyChunks } from "./utils/lazy-chunks.js";
import { formatMissingCloudflarePluginError, hasWranglerConfig } from "./deploy.js";
import { resolvePostcssStringPlugins } from "./plugins/postcss.js";
import { createClientCodeSplittingConfig, createClientManualChunks, createClientOutputConfig, getBuildBundlerOptions, getClientTreeshakeConfigForVite, withBuildBundlerOptions } from "./build/client-build-config.js";
import { augmentSsrManifestFromBundle, relativeWithinRoot, tryRealpathSync } from "./build/ssr-manifest.js";
import { stripServerExports } from "./plugins/strip-server-exports.js";
import { hasMdxFiles } from "./utils/mdx-scan.js";
import { scanPublicFileRoutes } from "./utils/public-routes.js";
import { staticExportApp, staticExportPages } from "./build/static-export.js";
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { loadEnv, parseAst, transformWithOxc } from "vite";
import { pathToFileURL } from "node:url";
import { randomBytes } from "node:crypto";
import MagicString from "magic-string";
import tsconfigPaths from "vite-tsconfig-paths";
import commonjs from "vite-plugin-commonjs";
//#region src/index.ts
installSocketErrorBackstop();
const __dirname = import.meta.dirname;
function resolveOptionalDependency(projectRoot, specifier) {
	try {
		return createRequire(path.join(projectRoot, "package.json")).resolve(specifier);
	} catch {}
	try {
		return createRequire(import.meta.url).resolve(specifier);
	} catch {}
	return null;
}
function resolveShimModulePath(shimsDir, moduleName) {
	for (const ext of [".ts", ".js"]) {
		const candidate = path.join(shimsDir, `${moduleName}${ext}`);
		if (fs.existsSync(candidate)) return candidate;
	}
	return path.join(shimsDir, `${moduleName}.js`);
}
function toRelativeFileEntry(root, absPath) {
	return path.relative(root, absPath).split(path.sep).join("/");
}
function isRecord(value) {
	return !!value && typeof value === "object" && !Array.isArray(value);
}
const TSCONFIG_FILES = ["tsconfig.json", "jsconfig.json"];
function resolveTsconfigPathCandidate(candidate) {
	const candidates = candidate.endsWith(".json") ? [candidate] : [
		candidate,
		`${candidate}.json`,
		path.join(candidate, "tsconfig.json")
	];
	for (const item of candidates) if (fs.existsSync(item) && fs.statSync(item).isFile()) return item;
	return null;
}
function resolveTsconfigExtends(configPath, specifier) {
	const fromDir = path.dirname(configPath);
	if (specifier.startsWith(".") || specifier.startsWith("/") || specifier.startsWith("\\")) return resolveTsconfigPathCandidate(path.resolve(fromDir, specifier));
	const requireFromConfig = createRequire(configPath);
	const candidates = [
		specifier,
		`${specifier}.json`,
		path.join(specifier, "tsconfig.json")
	];
	for (const item of candidates) try {
		return requireFromConfig.resolve(item);
	} catch {}
	return null;
}
function materializeTsconfigPathAliases(pathsConfig, baseUrl, projectRoot) {
	const aliases = {};
	for (const [find, rawTargets] of Object.entries(pathsConfig)) {
		const target = Array.isArray(rawTargets) ? rawTargets.find((value) => typeof value === "string") : typeof rawTargets === "string" ? rawTargets : null;
		if (!target) continue;
		if (find.includes("*") || target.includes("*")) {
			if (!find.endsWith("/*") || !target.endsWith("/*")) continue;
			if (find.indexOf("*") !== find.length - 1 || target.indexOf("*") !== target.length - 1) continue;
			const aliasKey = find.slice(0, -2);
			const targetDir = target.slice(0, -2);
			if (!aliasKey || !targetDir) continue;
			aliases[aliasKey] = toViteAliasReplacement(path.resolve(baseUrl, targetDir), projectRoot);
			continue;
		}
		aliases[find] = toViteAliasReplacement(path.resolve(baseUrl, target), projectRoot);
	}
	return aliases;
}
function toViteAliasReplacement(absolutePath, projectRoot) {
	const normalizedPath = absolutePath.replace(/\\/g, "/");
	const rootCandidates = new Set([projectRoot]);
	const realRoot = tryRealpathSync(projectRoot);
	if (realRoot) rootCandidates.add(realRoot);
	const pathCandidates = new Set([absolutePath]);
	const realPath = tryRealpathSync(absolutePath);
	if (realPath) pathCandidates.add(realPath);
	for (const rootCandidate of rootCandidates) for (const pathCandidate of pathCandidates) {
		if (pathCandidate === rootCandidate) return normalizedPath;
		const relativeId = relativeWithinRoot(rootCandidate, pathCandidate);
		if (relativeId) return "/" + relativeId;
	}
	return normalizedPath;
}
function loadTsconfigPathAliases(configPath, projectRoot, seen = /* @__PURE__ */ new Set()) {
	const normalizedPath = tryRealpathSync(configPath) ?? configPath;
	if (seen.has(normalizedPath)) return {};
	seen.add(normalizedPath);
	let parsed = null;
	try {
		parsed = parseStaticObjectLiteral(fs.readFileSync(normalizedPath, "utf-8"));
	} catch {
		return {};
	}
	if (!parsed) return {};
	let aliases = {};
	if (typeof parsed.extends === "string") {
		const extendedPath = resolveTsconfigExtends(normalizedPath, parsed.extends);
		if (extendedPath) aliases = loadTsconfigPathAliases(extendedPath, projectRoot, seen);
	}
	const compilerOptions = isRecord(parsed.compilerOptions) ? parsed.compilerOptions : null;
	const pathsConfig = compilerOptions && isRecord(compilerOptions.paths) ? compilerOptions.paths : null;
	if (!pathsConfig) return aliases;
	const baseUrl = compilerOptions && typeof compilerOptions.baseUrl === "string" ? compilerOptions.baseUrl : ".";
	const resolvedBaseUrl = path.resolve(path.dirname(normalizedPath), baseUrl);
	return {
		...aliases,
		...materializeTsconfigPathAliases(pathsConfig, resolvedBaseUrl, projectRoot)
	};
}
/**
* Detect Vite major version at runtime by resolving from cwd.
* The plugin may be installed in a workspace root with Vite 7 but used
* by a project that has Vite 8 — so we resolve from cwd, not from
* the plugin's own location.
*/
function getViteMajorVersion() {
	try {
		const vitePkg = createRequire(path.join(process.cwd(), "package.json"))("vite/package.json");
		const viteMajor = parseInt(vitePkg?.version, 10);
		if (vitePkg?.name === "vite" && Number.isFinite(viteMajor)) return viteMajor;
		const bundledViteMajor = parseInt(vitePkg?.bundledVersions?.vite, 10);
		if (Number.isFinite(bundledViteMajor)) return bundledViteMajor;
		console.warn(`[vinext] Could not determine Vite major version from ${vitePkg?.name ?? "vite/package.json"}; assuming Vite 7`);
		return 7;
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		console.warn(`[vinext] Failed to resolve vite/package.json (${message}); assuming Vite 7`);
		return 7;
	}
}
/**
* Read the vinext package version once at plugin load. Surfaced via
* `process.env.__NEXT_VERSION` define so `window.next.version` lands a
* real string instead of the `"vinext"` fallback. Resolved relative to
* this module's own `package.json`, not the project root.
*
* Defaults to `"vinext"` on read failure so a malformed install never
* breaks the build — only the diagnostic global loses fidelity.
*/
let _vinextVersionCache = null;
function getVinextVersion() {
	if (_vinextVersionCache !== null) return _vinextVersionCache;
	try {
		const pkgUrl = new URL("../package.json", import.meta.url);
		const pkg = JSON.parse(fs.readFileSync(pkgUrl, "utf-8"));
		_vinextVersionCache = typeof pkg.version === "string" ? pkg.version : "vinext";
	} catch {
		_vinextVersionCache = "vinext";
	}
	return _vinextVersionCache;
}
const _tsconfigAliasCache = /* @__PURE__ */ new Map();
function resolveTsconfigAliases(projectRoot) {
	if (_tsconfigAliasCache.has(projectRoot)) return _tsconfigAliasCache.get(projectRoot);
	let aliases = {};
	for (const name of TSCONFIG_FILES) {
		const candidate = path.join(projectRoot, name);
		if (!fs.existsSync(candidate)) continue;
		aliases = loadTsconfigPathAliases(candidate, projectRoot);
		break;
	}
	_tsconfigAliasCache.set(projectRoot, aliases);
	return aliases;
}
const VIRTUAL_SERVER_ENTRY = "virtual:vinext-server-entry";
const RESOLVED_SERVER_ENTRY = "\0" + VIRTUAL_SERVER_ENTRY;
const VIRTUAL_CLIENT_ENTRY = "virtual:vinext-client-entry";
const RESOLVED_CLIENT_ENTRY = "\0" + VIRTUAL_CLIENT_ENTRY;
const VIRTUAL_RSC_ENTRY = "virtual:vinext-rsc-entry";
const RESOLVED_RSC_ENTRY = "\0" + VIRTUAL_RSC_ENTRY;
const VIRTUAL_APP_SSR_ENTRY = "virtual:vinext-app-ssr-entry";
const RESOLVED_APP_SSR_ENTRY = "\0" + VIRTUAL_APP_SSR_ENTRY;
const VIRTUAL_APP_BROWSER_ENTRY = "virtual:vinext-app-browser-entry";
const RESOLVED_APP_BROWSER_ENTRY = "\0" + VIRTUAL_APP_BROWSER_ENTRY;
const RESOLVED_ROOT_PARAMS = "\0virtual:vinext-root-params";
/** Image file extensions handled by the vinext:image-imports plugin.
*  Shared between the Rolldown hook filter and the transform handler regex. */
const IMAGE_EXTS = "png|jpe?g|gif|webp|avif|svg|ico|bmp|tiff?";
/** Absolute path to vinext's shims directory, used by clientManualChunks. */
const _shimsDir = path.resolve(__dirname, "shims") + "/";
const _fontGoogleShimPath = resolveShimModulePath(_shimsDir, "font-google");
function isValidExportIdentifier(name) {
	return /^[$A-Z_a-z][$\w]*$/.test(name);
}
function generateRootParamsModule(rootParamNames) {
	const names = Array.from(new Set(rootParamNames)).filter(isValidExportIdentifier).sort();
	if (names.length === 0) return "export {};\n";
	const rootParamsShimPath = resolveShimModulePath(_shimsDir, "root-params");
	const exports = names.map((name) => `export function ${name}() { return getRootParam(${JSON.stringify(name)}); }`).join("\n");
	return `import { getRootParam } from ${JSON.stringify(rootParamsShimPath)};\n${exports}\n`;
}
/**
* Shims with a `.react-server.ts` variant for the RSC environment.
* Maps import specifier → base shim name. In the RSC env, resolveId
* appends `.react-server`; in other envs it resolves to the base.
*
* These MUST NOT appear in `nextShimMap` (resolve.alias) because Vite's
* alias plugin runs before user `enforce:"pre"` plugins — aliases are
* unoverridable. Keeping them out of the alias lets the resolveId hook
* control resolution per-environment.
*
* To add a new react-server shim:
*   1. Create `<name>.react-server.ts` in src/shims/
*   2. Add entries here for each import specifier.
*/
const _reactServerShims = new Map([
	["next/navigation", "navigation"],
	["next/navigation.js", "navigation"],
	["next/dist/client/components/navigation", "navigation"]
]);
const clientManualChunks = createClientManualChunks(_shimsDir);
const clientOutputConfig = createClientOutputConfig(clientManualChunks);
const clientCodeSplittingConfig = createClientCodeSplittingConfig(clientManualChunks);
function getClientOutputConfigForVite(viteMajorVersion) {
	return viteMajorVersion >= 8 ? { codeSplitting: clientCodeSplittingConfig } : clientOutputConfig;
}
function vinext(options = {}) {
	const viteMajorVersion = getViteMajorVersion();
	let root;
	let pagesDir;
	let appDir;
	let hasAppDir = false;
	let hasPagesDir = false;
	let nextConfig;
	let fileMatcher;
	let middlewarePath = null;
	let instrumentationPath = null;
	let instrumentationClientPath = null;
	let hasCloudflarePlugin = false;
	let warnedInlineNextConfigOverride = false;
	let hasNitroPlugin = false;
	let rscClassificationManifest = null;
	const shimsDir = path.resolve(__dirname, "shims");
	const canonicalize = (p) => tryRealpathSync(p) ?? p;
	const dynamicShimPaths = new Set([
		resolveShimModulePath(shimsDir, "headers"),
		resolveShimModulePath(shimsDir, "server"),
		resolveShimModulePath(shimsDir, "cache")
	].map(canonicalize));
	let nextShimMap = {};
	/**
	* Generate the virtual SSR server entry module.
	* This is the entry point for `vite build --ssr`.
	*/
	async function generateServerEntry$1() {
		return generateServerEntry(pagesDir, nextConfig, fileMatcher, middlewarePath, instrumentationPath);
	}
	/**
	* Generate the virtual client hydration entry module.
	* This is the entry point for `vite build` (client bundle).
	*
	* It maps route patterns to dynamic imports of page modules so Vite
	* code-splits each page into its own chunk. At runtime it reads
	* __NEXT_DATA__ to determine which page to hydrate.
	*/
	async function generateClientEntry$1() {
		return generateClientEntry(pagesDir, nextConfig, fileMatcher);
	}
	const autoRsc = options.rsc !== false;
	const earlyBaseDir = options.appDir ?? process.cwd();
	const earlyAppDirExists = !options.disableAppRouter && (fs.existsSync(path.join(earlyBaseDir, "app")) || fs.existsSync(path.join(earlyBaseDir, "src", "app")));
	let resolvedReactPath = null;
	let resolvedRscPath = null;
	let resolvedRscTransformsPath = null;
	resolvedReactPath = resolveOptionalDependency(earlyBaseDir, "@vitejs/plugin-react");
	resolvedRscPath = resolveOptionalDependency(earlyBaseDir, "@vitejs/plugin-rsc");
	resolvedRscTransformsPath = resolveOptionalDependency(earlyBaseDir, "@vitejs/plugin-rsc/transforms");
	let rscPluginPromise = null;
	if (earlyAppDirExists && autoRsc) {
		if (!resolvedRscPath) throw new Error("vinext: App Router detected but @vitejs/plugin-rsc is not installed.\nRun: " + detectPackageManager(process.cwd()) + " @vitejs/plugin-rsc");
		rscPluginPromise = import(pathToFileURL(resolvedRscPath).href).then((mod) => {
			const rsc = mod.default;
			return rsc({ entries: {
				rsc: VIRTUAL_RSC_ENTRY,
				ssr: VIRTUAL_APP_SSR_ENTRY,
				client: VIRTUAL_APP_BROWSER_ENTRY
			} });
		}).catch((cause) => {
			throw new Error("vinext: Failed to load @vitejs/plugin-rsc.", { cause });
		});
	}
	const reactOptions = options.react && options.react !== true ? options.react : void 0;
	let reactPluginPromise = null;
	if (options.react !== false) {
		if (!resolvedReactPath) throw new Error("vinext: @vitejs/plugin-react is not installed.\nRun: " + detectPackageManager(process.cwd()) + " @vitejs/plugin-react");
		reactPluginPromise = import(pathToFileURL(resolvedReactPath).href).then((mod) => mod.default(reactOptions)).catch((cause) => {
			throw new Error("vinext: Failed to load @vitejs/plugin-react.", { cause });
		});
	}
	const imageImportDimCache = /* @__PURE__ */ new Map();
	let mdxDelegate = null;
	let mdxDelegatePromise = null;
	let hasUserMdxPlugin = false;
	let warnedMissingMdxPlugin = false;
	async function ensureMdxDelegate(reason) {
		if (mdxDelegate || hasUserMdxPlugin) return mdxDelegate;
		if (!mdxDelegatePromise) mdxDelegatePromise = (async () => {
			try {
				const mdxRollup = await import("@mdx-js/rollup");
				const mdxFactory = mdxRollup.default ?? mdxRollup;
				const mdxOpts = {};
				if (nextConfig.mdx) {
					if (nextConfig.mdx.remarkPlugins) mdxOpts.remarkPlugins = nextConfig.mdx.remarkPlugins;
					if (nextConfig.mdx.rehypePlugins) mdxOpts.rehypePlugins = nextConfig.mdx.rehypePlugins;
					if (nextConfig.mdx.recmaPlugins) mdxOpts.recmaPlugins = nextConfig.mdx.recmaPlugins;
				}
				const delegate = mdxFactory(mdxOpts);
				mdxDelegate = delegate;
				if (reason === "detected") if (nextConfig.mdx) console.log("[vinext] Auto-injected @mdx-js/rollup with remark/rehype plugins from next.config");
				else console.log("[vinext] Auto-injected @mdx-js/rollup for MDX support");
				else console.log("[vinext] Auto-injected @mdx-js/rollup for on-demand MDX support");
				return delegate;
			} catch {
				if (reason === "detected" && !warnedMissingMdxPlugin) {
					warnedMissingMdxPlugin = true;
					console.warn("[vinext] MDX files detected but @mdx-js/rollup is not installed. Install it with: " + detectPackageManager(process.cwd()) + " @mdx-js/rollup");
				}
				return null;
			}
		})();
		return mdxDelegatePromise;
	}
	const plugins = [
		...viteMajorVersion >= 8 ? [] : [tsconfigPaths()],
		reactPluginPromise,
		commonjs(),
		...viteMajorVersion >= 8 ? [{
			name: "vinext:jsx-in-js",
			enforce: "pre",
			async transform(code, id) {
				const cleanId = id.split("?")[0];
				if (!/\.(m?js)$/.test(cleanId)) return;
				if (cleanId.includes("/node_modules/")) return;
				const result = await transformWithOxc(code, id, {
					lang: "jsx",
					jsx: { runtime: "automatic" },
					sourcemap: true
				});
				return {
					code: result.code,
					map: result.map
				};
			}
		}] : [],
		{
			name: "vinext:config",
			enforce: "pre",
			async config(config, env) {
				root = config.root ?? process.cwd();
				const userResolve = config.resolve;
				const shouldEnableNativeTsconfigPaths = viteMajorVersion >= 8 && userResolve?.tsconfigPaths === void 0;
				const tsconfigPathAliases = resolveTsconfigAliases(root);
				const mode = env?.mode ?? "development";
				const dotenvVars = loadEnv(mode, config.envDir ?? root, "");
				for (const [key, value] of Object.entries(dotenvVars)) if (process.env[key] === void 0) process.env[key] = value;
				let resolvedNodeEnv;
				if (mode === "test") resolvedNodeEnv = "test";
				else if (env?.command === "build") resolvedNodeEnv = "production";
				else resolvedNodeEnv = "development";
				if (process.env.NODE_ENV !== resolvedNodeEnv) process.env.NODE_ENV = resolvedNodeEnv;
				let baseDir;
				if (options.appDir) baseDir = path.isAbsolute(options.appDir) ? options.appDir : path.resolve(root, options.appDir);
				else {
					const hasRootApp = fs.existsSync(path.join(root, "app"));
					const hasRootPages = fs.existsSync(path.join(root, "pages"));
					const hasSrcApp = fs.existsSync(path.join(root, "src", "app"));
					const hasSrcPages = fs.existsSync(path.join(root, "src", "pages"));
					if (hasRootApp || hasRootPages) baseDir = root;
					else if (hasSrcApp || hasSrcPages) baseDir = path.join(root, "src");
					else baseDir = root;
				}
				pagesDir = path.join(baseDir, "pages");
				appDir = path.join(baseDir, "app");
				hasPagesDir = fs.existsSync(pagesDir);
				hasAppDir = !options.disableAppRouter && fs.existsSync(appDir);
				if (!nextConfig) {
					const phase = env?.command === "build" ? PHASE_PRODUCTION_BUILD : PHASE_DEVELOPMENT_SERVER;
					let rawConfig;
					if (options.nextConfig) {
						const diskConfigPath = findNextConfigPath(root);
						if (diskConfigPath && !warnedInlineNextConfigOverride) {
							warnedInlineNextConfigOverride = true;
							console.warn(`[vinext] vinext({ nextConfig }) overrides ${path.basename(diskConfigPath)}. Remove one of the config sources to avoid drift.`);
						}
						rawConfig = await resolveNextConfigInput(options.nextConfig, phase);
					} else rawConfig = await loadNextConfig(root, phase);
					nextConfig = await resolveNextConfig(rawConfig, root);
				}
				fileMatcher = createValidFileMatcher(nextConfig.pageExtensions);
				instrumentationPath = findInstrumentationFile(root, fileMatcher);
				instrumentationClientPath = findInstrumentationClientFile(root, fileMatcher);
				middlewarePath = findMiddlewareFile(root, fileMatcher);
				const defines = getNextPublicEnvDefines();
				if (!config.define || typeof config.define !== "object" || !("process.env.NODE_ENV" in config.define)) defines["process.env.NODE_ENV"] = JSON.stringify(resolvedNodeEnv);
				for (const [key, value] of Object.entries(nextConfig.env)) {
					if (key === "NODE_ENV") continue;
					defines[`process.env.${key}`] = JSON.stringify(value);
				}
				defines["process.env.__NEXT_ROUTER_BASEPATH"] = JSON.stringify(nextConfig.basePath);
				defines["process.env.__VINEXT_IMAGE_REMOTE_PATTERNS"] = JSON.stringify(JSON.stringify(nextConfig.images?.remotePatterns ?? []));
				defines["process.env.__VINEXT_IMAGE_DOMAINS"] = JSON.stringify(JSON.stringify(nextConfig.images?.domains ?? []));
				{
					const deviceSizes = nextConfig.images?.deviceSizes ?? [
						640,
						750,
						828,
						1080,
						1200,
						1920,
						2048,
						3840
					];
					const imageSizes = nextConfig.images?.imageSizes ?? [
						16,
						32,
						48,
						64,
						96,
						128,
						256,
						384
					];
					defines["process.env.__VINEXT_IMAGE_DEVICE_SIZES"] = JSON.stringify(JSON.stringify(deviceSizes));
					defines["process.env.__VINEXT_IMAGE_SIZES"] = JSON.stringify(JSON.stringify(imageSizes));
				}
				defines["process.env.__VINEXT_IMAGE_DANGEROUSLY_ALLOW_SVG"] = JSON.stringify(String(nextConfig.images?.dangerouslyAllowSVG ?? false));
				defines["process.env.__VINEXT_IMAGE_DANGEROUSLY_ALLOW_LOCAL_IP"] = JSON.stringify(String(nextConfig.images?.dangerouslyAllowLocalIP ?? false));
				defines["process.env.__VINEXT_DRAFT_SECRET"] = JSON.stringify(crypto.randomUUID());
				defines["process.env.__VINEXT_BUILD_ID"] = JSON.stringify(nextConfig.buildId);
				defines["process.env.__VINEXT_DEPLOYMENT_ID"] = JSON.stringify(nextConfig.deploymentId ?? "");
				defines["process.env.__NEXT_VERSION"] = JSON.stringify(getVinextVersion());
				nextShimMap = Object.fromEntries(Object.entries({
					"next/link": path.join(shimsDir, "link"),
					"next/head": path.join(shimsDir, "head"),
					"next/router": path.join(shimsDir, "router"),
					"next/compat/router": path.join(shimsDir, "compat-router"),
					"next/image": path.join(shimsDir, "image"),
					"next/legacy/image": path.join(shimsDir, "legacy-image"),
					"next/dynamic": path.join(shimsDir, "dynamic"),
					"next/app": path.join(shimsDir, "app"),
					"next/document": path.join(shimsDir, "document"),
					"next/config": path.join(shimsDir, "config"),
					"next/script": path.join(shimsDir, "script"),
					"next/server": path.join(shimsDir, "server"),
					"next/headers": path.join(shimsDir, "headers"),
					"next/font/google": path.join(shimsDir, "font-google"),
					"next/font/local": path.join(shimsDir, "font-local"),
					"next/cache": path.join(shimsDir, "cache"),
					"next/form": path.join(shimsDir, "form"),
					"next/og": path.join(shimsDir, "og"),
					"next/web-vitals": path.join(shimsDir, "web-vitals"),
					"next/amp": path.join(shimsDir, "amp"),
					"next/offline": path.join(shimsDir, "offline"),
					"next/error": path.join(shimsDir, "error"),
					"next/constants": path.join(shimsDir, "constants"),
					"next/dist/shared/lib/app-router-context.shared-runtime": path.join(shimsDir, "internal", "app-router-context"),
					"next/dist/shared/lib/app-router-context": path.join(shimsDir, "internal", "app-router-context"),
					"next/dist/shared/lib/router-context.shared-runtime": path.join(shimsDir, "internal", "router-context"),
					"next/dist/shared/lib/utils": path.join(shimsDir, "internal", "utils"),
					"next/dist/server/api-utils": path.join(shimsDir, "internal", "api-utils"),
					"next/dist/server/web/spec-extension/cookies": path.join(shimsDir, "internal", "cookies"),
					"next/dist/compiled/@edge-runtime/cookies": path.join(shimsDir, "internal", "cookies"),
					"next/dist/server/app-render/work-unit-async-storage.external": path.join(shimsDir, "internal", "work-unit-async-storage"),
					"next/dist/client/components/work-unit-async-storage.external": path.join(shimsDir, "internal", "work-unit-async-storage"),
					"next/dist/client/components/request-async-storage.external": path.join(shimsDir, "internal", "work-unit-async-storage"),
					"next/dist/client/components/request-async-storage": path.join(shimsDir, "internal", "work-unit-async-storage"),
					"next/dist/server/request/root-params": path.join(shimsDir, "root-params"),
					"next/dist/server/config-shared": path.join(shimsDir, "internal", "utils"),
					"server-only": path.join(shimsDir, "server-only"),
					"client-only": path.join(shimsDir, "client-only"),
					"vinext/error-boundary": path.join(shimsDir, "error-boundary"),
					"vinext/layout-segment-context": path.join(shimsDir, "layout-segment-context"),
					"vinext/metadata": path.join(shimsDir, "metadata"),
					"vinext/fetch-cache": path.join(shimsDir, "fetch-cache"),
					"vinext/cache-runtime": path.join(shimsDir, "cache-runtime"),
					"vinext/navigation-state": path.join(shimsDir, "navigation-state"),
					"vinext/unified-request-context": path.join(shimsDir, "unified-request-context"),
					"vinext/router-state": path.join(shimsDir, "router-state"),
					"vinext/head-state": path.join(shimsDir, "head-state"),
					"vinext/i18n-state": path.join(shimsDir, "i18n-state"),
					"vinext/i18n-context": path.join(shimsDir, "i18n-context"),
					"vinext/cache": path.resolve(__dirname, "cache"),
					"vinext/instrumentation": path.resolve(__dirname, "server", "instrumentation"),
					"vinext/instrumentation-client": path.resolve(__dirname, "client", "instrumentation-client"),
					"vinext/html": path.resolve(__dirname, "server", "html"),
					"private-next-instrumentation-client": instrumentationClientPath ?? path.resolve(__dirname, "client", "empty-module")
				}).flatMap(([k, v]) => k.startsWith("next/") ? [[k, v], [`${k}.js`, v]] : [[k, v]]));
				const pluginsFlat = [];
				function flattenPlugins(arr) {
					for (const p of arr) if (Array.isArray(p)) flattenPlugins(p);
					else if (p) pluginsFlat.push(p);
				}
				flattenPlugins(config.plugins ?? []);
				hasCloudflarePlugin = pluginsFlat.some((p) => p && typeof p === "object" && "name" in p && typeof p.name === "string" && (p.name === "vite-plugin-cloudflare" || p.name.startsWith("vite-plugin-cloudflare:")));
				hasNitroPlugin = pluginsFlat.some((p) => p && typeof p === "object" && "name" in p && typeof p.name === "string" && (p.name === "nitro" || p.name.startsWith("nitro:")));
				let postcssOverride;
				if (!config.css?.postcss || typeof config.css.postcss === "string") postcssOverride = await resolvePostcssStringPlugins(root);
				hasUserMdxPlugin = pluginsFlat.some((p) => p && typeof p === "object" && "name" in p && typeof p.name === "string" && (p.name === "@mdx-js/rollup" || p.name === "mdx"));
				if (!hasUserMdxPlugin && hasMdxFiles(root, hasAppDir ? appDir : null, hasPagesDir ? pagesDir : null)) await ensureMdxDelegate("detected");
				const isSSR = !!config.build?.ssr;
				const isMultiEnv = hasAppDir || hasCloudflarePlugin || hasNitroPlugin;
				const viteConfig = {
					appType: "custom",
					build: { ...withBuildBundlerOptions(viteMajorVersion, {
						onwarn: (() => {
							const userOnwarn = getBuildBundlerOptions(config.build)?.onwarn;
							return (warning, defaultHandler) => {
								if (warning.code === "MODULE_LEVEL_DIRECTIVE" && (warning.message?.includes("\"use client\"") || warning.message?.includes("\"use server\""))) return;
								if (warning.code === "IMPORT_IS_UNDEFINED" && warning.message?.includes("generateStaticParams")) return;
								if (warning.code === "IMPORT_IS_UNDEFINED" && /Import `(?:default|proxy|middleware)` will always be undefined/.test(warning.message ?? "") && /\b(?:proxy|middleware)\.\w+\b/.test(warning.message ?? "") && (warning.message?.includes("virtual:vinext-rsc-entry") || warning.message?.includes("virtual:vinext-server-entry"))) return;
								if (userOnwarn) userOnwarn(warning, defaultHandler);
								else defaultHandler(warning);
							};
						})(),
						...!isSSR && !isMultiEnv ? { treeshake: getClientTreeshakeConfigForVite(viteMajorVersion) } : {},
						...!isSSR && !isMultiEnv ? { output: getClientOutputConfigForVite(viteMajorVersion) } : {}
					}) },
					server: { cors: {
						preflightContinue: true,
						origin: /^https?:\/\/(?:(?:[^:]+\.)?localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$/
					} },
					...hasCloudflarePlugin || hasNitroPlugin ? {} : config.ssr?.external === true ? { ssr: { external: true } } : { ssr: {
						external: [
							"react",
							"react-dom",
							"react-dom/server",
							"ipaddr.js"
						],
						noExternal: true
					} },
					resolve: {
						alias: {
							...tsconfigPathAliases,
							...nextConfig.aliases,
							...nextShimMap
						},
						dedupe: [
							"react",
							"react-dom",
							"react/jsx-runtime",
							"react/jsx-dev-runtime"
						],
						...shouldEnableNativeTsconfigPaths ? { tsconfigPaths: true } : {}
					},
					...viteMajorVersion >= 8 ? { oxc: { jsx: { runtime: "automatic" } } } : { esbuild: { jsx: "automatic" } },
					define: defines,
					...nextConfig.basePath ? { base: nextConfig.basePath + "/" } : {},
					...postcssOverride ? { css: { postcss: postcssOverride } } : {}
				};
				const nextServerExternal = nextConfig?.serverExternalPackages ?? [];
				const userSsrExternal = Array.isArray(config.ssr?.external) ? [...config.ssr.external, ...nextServerExternal] : config.ssr?.external === true ? true : nextServerExternal;
				const incomingExclude = config.optimizeDeps?.exclude ?? [];
				const incomingInclude = config.optimizeDeps?.include ?? [];
				const depOptimizeAliasPlugin = {
					name: "vinext:dep-optimize-alias",
					resolveId(id) {
						const shimBase = _reactServerShims.get(id);
						if (shimBase !== void 0) return resolveShimModulePath(shimsDir, shimBase);
					}
				};
				viteConfig.optimizeDeps = {
					exclude: mergeOptimizeDepsExclude(incomingExclude, VINEXT_OPTIMIZE_DEPS_EXCLUDE, ["@tailwindcss/oxide"]),
					...incomingInclude.length > 0 ? { include: incomingInclude } : {},
					rolldownOptions: { plugins: [depOptimizeAliasPlugin] }
				};
				const pagesOptimizeEntries = !hasAppDir ? [...hasPagesDir ? [toRelativeFileEntry(root, pagesDir) + "/**/*.{tsx,ts,jsx,js}"] : [], ...[instrumentationPath, instrumentationClientPath].flatMap((entry) => entry ? [toRelativeFileEntry(root, entry)] : [])] : [];
				if (hasAppDir) {
					const appEntries = [`${path.relative(root, appDir)}/**/*.{tsx,ts,jsx,js}`];
					const explicitInstrumentationEntries = [instrumentationPath, instrumentationClientPath].flatMap((entry) => entry ? [toRelativeFileEntry(root, entry)] : []);
					const optimizeEntries = [...new Set([...appEntries, ...explicitInstrumentationEntries])];
					viteConfig.environments = {
						rsc: {
							...hasCloudflarePlugin || hasNitroPlugin ? {} : { resolve: {
								external: userSsrExternal === true ? true : [
									"satori",
									"@resvg/resvg-js",
									"yoga-wasm-web",
									...userSsrExternal
								],
								...userSsrExternal === true ? {} : { noExternal: true }
							} },
							optimizeDeps: {
								exclude: mergeOptimizeDepsExclude(incomingExclude, VINEXT_OPTIMIZE_DEPS_EXCLUDE),
								entries: optimizeEntries
							},
							build: {
								outDir: options.rscOutDir ?? "dist/server",
								...withBuildBundlerOptions(viteMajorVersion, { input: { index: VIRTUAL_RSC_ENTRY } })
							}
						},
						ssr: {
							...hasCloudflarePlugin || hasNitroPlugin ? {} : { resolve: {
								external: userSsrExternal === true ? true : [...userSsrExternal, "ipaddr.js"],
								...userSsrExternal === true ? {} : { noExternal: true }
							} },
							optimizeDeps: {
								exclude: mergeOptimizeDepsExclude(incomingExclude, VINEXT_OPTIMIZE_DEPS_EXCLUDE, userSsrExternal === true ? SSR_EXTERNAL_REACT_ENTRIES : []),
								entries: optimizeEntries
							},
							build: {
								outDir: options.ssrOutDir ?? "dist/server/ssr",
								...withBuildBundlerOptions(viteMajorVersion, { input: { index: VIRTUAL_APP_SSR_ENTRY } })
							}
						},
						client: {
							consumer: "client",
							optimizeDeps: {
								exclude: mergeOptimizeDepsExclude(incomingExclude, VINEXT_OPTIMIZE_DEPS_EXCLUDE, nextServerExternal),
								entries: optimizeEntries,
								include: [...new Set([
									...incomingInclude,
									"react",
									"react-dom",
									"react-dom/client",
									"react/jsx-runtime",
									"react/jsx-dev-runtime"
								])]
							},
							build: {
								...hasCloudflarePlugin ? { manifest: true } : {},
								...withBuildBundlerOptions(viteMajorVersion, {
									input: { index: VIRTUAL_APP_BROWSER_ENTRY },
									output: getClientOutputConfigForVite(viteMajorVersion),
									treeshake: getClientTreeshakeConfigForVite(viteMajorVersion)
								})
							}
						}
					};
				} else if (hasCloudflarePlugin) viteConfig.environments = { client: {
					consumer: "client",
					optimizeDeps: pagesOptimizeEntries.length > 0 ? { entries: pagesOptimizeEntries } : void 0,
					build: {
						manifest: true,
						ssrManifest: true,
						...withBuildBundlerOptions(viteMajorVersion, {
							input: { index: VIRTUAL_CLIENT_ENTRY },
							output: getClientOutputConfigForVite(viteMajorVersion),
							treeshake: getClientTreeshakeConfigForVite(viteMajorVersion)
						})
					}
				} };
				else if (!isSSR && !getBuildBundlerOptions(config.build)?.input) viteConfig.environments = {
					client: {
						consumer: "client",
						optimizeDeps: pagesOptimizeEntries.length > 0 ? { entries: pagesOptimizeEntries } : void 0,
						build: {
							outDir: "dist/client",
							manifest: true,
							ssrManifest: true,
							...withBuildBundlerOptions(viteMajorVersion, {
								input: { index: VIRTUAL_CLIENT_ENTRY },
								output: getClientOutputConfigForVite(viteMajorVersion),
								treeshake: getClientTreeshakeConfigForVite(viteMajorVersion)
							})
						}
					},
					ssr: {
						resolve: {
							external: [
								"react",
								"react-dom",
								"react-dom/server",
								"ipaddr.js"
							],
							noExternal: true
						},
						build: {
							outDir: "dist/server",
							...withBuildBundlerOptions(viteMajorVersion, {
								input: { index: VIRTUAL_SERVER_ENTRY },
								output: { entryFileNames: "entry.js" }
							})
						}
					}
				};
				if (pagesOptimizeEntries.length > 0 && !hasCloudflarePlugin) viteConfig.optimizeDeps = {
					...viteConfig.optimizeDeps,
					entries: pagesOptimizeEntries
				};
				return viteConfig;
			},
			configResolved(config) {
				if (hasAppDir) {
					const ssrEnv = config.environments?.ssr;
					if (ssrEnv?.resolve?.external === true && Array.isArray(ssrEnv.resolve.noExternal)) ssrEnv.resolve.noExternal = ssrEnv.resolve.noExternal.filter((entry) => typeof entry !== "string" || !SSR_EXTERNAL_REACT_ENTRIES.includes(entry));
				}
				// @vitejs/plugin-react AND the user also registers it manually, the
				if (reactPluginPromise) {
					const reactRootPlugins = config.plugins.filter((p) => p && typeof p === "object" && "name" in p && typeof p.name === "string" && p.name.startsWith("vite:react"));
					const counts = /* @__PURE__ */ new Map();
					for (const plugin of reactRootPlugins) counts.set(plugin.name, (counts.get(plugin.name) ?? 0) + 1);
					if ([...counts.values()].some((count) => count > 1)) throw new Error("[vinext] Duplicate @vitejs/plugin-react detected.\n         vinext auto-registers @vitejs/plugin-react by default.\n         Your config also registers it manually, which duplicates React transforms.\n\n         Fix: remove the explicit react() call from your plugins array.\n         Or: pass react: false to vinext() if you want to configure react() yourself.");
				}
				// @vitejs/plugin-rsc AND the user also registers it manually, the
				if (rscPluginPromise) {
					if (config.plugins.filter((p) => p && typeof p === "object" && "name" in p && p.name === "rsc").length > 1) throw new Error("[vinext] Duplicate @vitejs/plugin-rsc detected.\n         vinext auto-registers @vitejs/plugin-rsc when app/ is detected.\n         Your config also registers it manually, which doubles build time.\n\n         Fix: remove the explicit rsc() call from your plugins array.\n         Or: pass rsc: false to vinext() if you want to configure rsc() yourself.");
				}
				if (config.command === "build" && !hasCloudflarePlugin && !hasNitroPlugin && hasWranglerConfig(root) && !options.disableAppRouter) throw new Error(formatMissingCloudflarePluginError({
					isAppRouter: hasAppDir,
					configFile: config.configFile
				}));
			},
			resolveId: {
				filter: { id: /(?:next\/|virtual:vinext-)/ },
				handler(id) {
					const cleanId = id.startsWith("\0") ? id.slice(1) : id;
					if (cleanId === VIRTUAL_SERVER_ENTRY) return RESOLVED_SERVER_ENTRY;
					if (cleanId === VIRTUAL_CLIENT_ENTRY) return RESOLVED_CLIENT_ENTRY;
					if (cleanId.endsWith("/" + VIRTUAL_SERVER_ENTRY) || cleanId.endsWith("\\" + VIRTUAL_SERVER_ENTRY)) return RESOLVED_SERVER_ENTRY;
					if (cleanId.endsWith("/" + VIRTUAL_CLIENT_ENTRY) || cleanId.endsWith("\\" + VIRTUAL_CLIENT_ENTRY)) return RESOLVED_CLIENT_ENTRY;
					if (cleanId === VIRTUAL_RSC_ENTRY) return RESOLVED_RSC_ENTRY;
					if (cleanId === VIRTUAL_APP_SSR_ENTRY) return RESOLVED_APP_SSR_ENTRY;
					if (cleanId === VIRTUAL_APP_BROWSER_ENTRY) return RESOLVED_APP_BROWSER_ENTRY;
					if (cleanId === "next/root-params" || cleanId === "next/root-params.js") return RESOLVED_ROOT_PARAMS;
					if (cleanId.startsWith("virtual:vinext-google-fonts?")) return RESOLVED_VIRTUAL_GOOGLE_FONTS + cleanId.slice(VIRTUAL_GOOGLE_FONTS.length);
					if (cleanId.endsWith("/" + VIRTUAL_RSC_ENTRY) || cleanId.endsWith("\\" + VIRTUAL_RSC_ENTRY)) return RESOLVED_RSC_ENTRY;
					if (cleanId.endsWith("/" + VIRTUAL_APP_SSR_ENTRY) || cleanId.endsWith("\\" + VIRTUAL_APP_SSR_ENTRY)) return RESOLVED_APP_SSR_ENTRY;
					if (cleanId.endsWith("/" + VIRTUAL_APP_BROWSER_ENTRY) || cleanId.endsWith("\\" + VIRTUAL_APP_BROWSER_ENTRY)) return RESOLVED_APP_BROWSER_ENTRY;
					if (cleanId.includes("/virtual:vinext-google-fonts?") || cleanId.includes("\\virtual:vinext-google-fonts?")) {
						const queryIndex = cleanId.indexOf(VIRTUAL_GOOGLE_FONTS + "?");
						return RESOLVED_VIRTUAL_GOOGLE_FONTS + cleanId.slice(queryIndex + VIRTUAL_GOOGLE_FONTS.length);
					}
					const reactServerShim = _reactServerShims.get(cleanId);
					if (reactServerShim !== void 0) return resolveShimModulePath(_shimsDir, this.environment?.name === "rsc" ? `${reactServerShim}.react-server` : reactServerShim);
				}
			},
			async load(id) {
				if (id === RESOLVED_SERVER_ENTRY) return await generateServerEntry$1();
				if (id === RESOLVED_CLIENT_ENTRY) return await generateClientEntry$1();
				if (id === RESOLVED_RSC_ENTRY && hasAppDir) {
					const routes = await appRouter(appDir, nextConfig?.pageExtensions, fileMatcher);
					const metaRoutes = scanMetadataFiles(appDir);
					const globalErrorPath = findFileWithExts(appDir, "global-error", fileMatcher);
					rscClassificationManifest = collectRouteClassificationManifest(routes);
					return generateRscEntry(appDir, routes, middlewarePath, metaRoutes, globalErrorPath, nextConfig?.basePath, nextConfig?.trailingSlash, {
						redirects: nextConfig?.redirects,
						rewrites: nextConfig?.rewrites,
						headers: nextConfig?.headers,
						allowedOrigins: nextConfig?.serverActionsAllowedOrigins,
						allowedDevOrigins: nextConfig?.allowedDevOrigins,
						bodySizeLimit: nextConfig?.serverActionsBodySizeLimit,
						expireTime: nextConfig?.expireTime,
						i18n: nextConfig?.i18n,
						hasPagesDir,
						publicFiles: scanPublicFileRoutes(root)
					}, instrumentationPath);
				}
				if (id === RESOLVED_ROOT_PARAMS) return generateRootParamsModule((hasAppDir ? await appRouter(appDir, nextConfig?.pageExtensions, fileMatcher) : []).flatMap((route) => route.rootParamNames ?? []));
				if (id === RESOLVED_APP_SSR_ENTRY && hasAppDir) return generateSsrEntry(hasPagesDir);
				if (id === RESOLVED_APP_BROWSER_ENTRY && hasAppDir) return generateBrowserEntry(await appRouter(appDir, nextConfig?.pageExtensions, fileMatcher));
				if (id.startsWith("\0virtual:vinext-google-fonts?")) return generateGoogleFontsVirtualModule(id, _fontGoogleShimPath);
			},
			// @vitejs/plugin-rsc runs the RSC environment build in two phases:
			generateBundle(_options, bundle) {
				if (this.environment?.name !== "rsc") return;
				if (!rscClassificationManifest) return;
				const enableClassificationDebug = Boolean(process.env.VINEXT_DEBUG_CLASSIFICATION);
				const chunks = [];
				const chunksByFileName = /* @__PURE__ */ new Map();
				for (const chunk of Object.values(bundle)) {
					if (chunk.type !== "chunk") continue;
					chunks.push({
						code: chunk.code,
						fileName: chunk.fileName
					});
					chunksByFileName.set(chunk.fileName, chunk);
				}
				const patchPlan = planRouteClassificationInjection({
					canonicalizeLayoutPath: canonicalize,
					chunks,
					dynamicShimPaths,
					enableDebugReasons: enableClassificationDebug,
					manifest: rscClassificationManifest,
					moduleInfo: { getModuleInfo: (moduleId) => {
						const info = this.getModuleInfo(moduleId);
						if (!info) return null;
						return {
							importedIds: info.importedIds ?? [],
							dynamicImportedIds: info.dynamicallyImportedIds ?? []
						};
					} }
				});
				if (patchPlan.kind === "skip") return;
				const target = chunksByFileName.get(patchPlan.fileName);
				if (!target) throw new Error(`vinext: build-time classification — patch target ${patchPlan.fileName} disappeared from the RSC bundle`);
				target.code = patchPlan.code;
				target.map = patchPlan.map;
				rscClassificationManifest = null;
			}
		},
		asyncHooksStubPlugin,
		createInstrumentationClientTransformPlugin(() => instrumentationClientPath),
		...options.experimental?.clientReferenceDedup ? [clientReferenceDedupPlugin()] : [],
		{
			name: "vinext:mdx",
			enforce: "pre",
			config(config, env) {
				if (!mdxDelegate?.config) return;
				const hook = mdxDelegate.config;
				return (typeof hook === "function" ? hook : hook.handler).call(this, config, env);
			},
			async transform(code, id, options) {
				if (id.includes("?")) return;
				if (!id.toLowerCase().endsWith(".mdx")) return;
				const delegate = mdxDelegate ?? await ensureMdxDelegate("on-demand");
				if (delegate?.transform) {
					const hook = delegate.transform;
					return (typeof hook === "function" ? hook : hook.handler).call(this, code, id, options);
				}
				if (!hasUserMdxPlugin) throw new Error(`[vinext] Encountered MDX module ${id} but no MDX plugin is configured. Install @mdx-js/rollup or register an MDX plugin manually.`);
			}
		},
		{
			name: "vinext:react-canary",
			enforce: "pre",
			resolveId(id) {
				if (id === "virtual:vinext-react-canary") return "\0virtual:vinext-react-canary";
			},
			load(id) {
				if (id === "\0virtual:vinext-react-canary") return [
					`export * from "react";`,
					`export { default } from "react";`,
					`import * as _React from "react";`,
					`export const ViewTransition = _React.ViewTransition || function ViewTransition({ children }) { return children; };`,
					`export const addTransitionType = _React.addTransitionType || function addTransitionType() {};`
				].join("\n");
			},
			transform(code, id) {
				if (id.includes("node_modules")) return null;
				if (id.startsWith("\0")) return null;
				if (!/\.(tsx?|jsx?|mjs)$/.test(id)) return null;
				if (!(code.includes("ViewTransition") || code.includes("addTransitionType")) || !/from\s+['"]react['"]/.test(code)) return null;
				if (!/import\s*\{[^}]*(ViewTransition|addTransitionType)[^}]*\}\s*from\s*['"]react['"]/.test(code)) return null;
				const result = code.replace(/from\s*['"]react['"]/g, "from \"virtual:vinext-react-canary\"");
				if (result !== code) return {
					code: result,
					map: null
				};
				return null;
			}
		},
		{
			name: "vinext:pages-router",
			hotUpdate(options) {
				if (!hasPagesDir || hasAppDir) return;
				if (options.file.startsWith(pagesDir) && fileMatcher.extensionRegex.test(options.file)) {
					options.server.environments.client.hot.send({ type: "full-reload" });
					return [];
				}
			},
			configureServer(server) {
				const pageExtensions = fileMatcher.extensionRegex;
				let pagesRunner = null;
				function getPagesRunner() {
					if (!pagesRunner) pagesRunner = createDirectRunner(server.environments["ssr"] ?? Object.values(server.environments).find((e) => e !== server.environments["rsc"]) ?? Object.values(server.environments)[0]);
					return pagesRunner;
				}
				/**
				* Invalidate the virtual RSC entry module in Vite's module graph.
				*
				* The App Router route table is baked into the virtual RSC entry
				* at generation time. When routes are added or removed, clearing
				* the route cache alone is not enough: the virtual module must
				* also be invalidated so Vite re-calls the load() hook to
				* regenerate the entry with the updated route table.
				*/
				function invalidateRscEntryModule() {
					const rscEnv = server.environments["rsc"];
					if (!rscEnv) return;
					const mod = rscEnv.moduleGraph.getModuleById(RESOLVED_RSC_ENTRY);
					if (mod) {
						rscEnv.moduleGraph.invalidateModule(mod);
						rscEnv.hot.send({ type: "full-reload" });
					}
				}
				function invalidateRootParamsModule() {
					for (const env of Object.values(server.environments)) {
						const mod = env.moduleGraph.getModuleById(RESOLVED_ROOT_PARAMS);
						if (mod) env.moduleGraph.invalidateModule(mod);
					}
				}
				function invalidateAppRoutingModules() {
					invalidateAppRouteCache();
					invalidateRscEntryModule();
					invalidateRootParamsModule();
				}
				server.httpServer?.on("connection", (socket) => {
					socket.on("error", () => {});
				});
				server.watcher.on("add", (filePath) => {
					if (hasPagesDir && filePath.startsWith(pagesDir) && pageExtensions.test(filePath)) invalidateRouteCache(pagesDir);
					if (hasAppDir && shouldInvalidateAppRouteFile(appDir, filePath, fileMatcher)) invalidateAppRoutingModules();
				});
				server.watcher.on("unlink", (filePath) => {
					if (hasPagesDir && filePath.startsWith(pagesDir) && pageExtensions.test(filePath)) invalidateRouteCache(pagesDir);
					if (hasAppDir && shouldInvalidateAppRouteFile(appDir, filePath, fileMatcher)) invalidateAppRoutingModules();
				});
				server.middlewares.use((req, res, next) => {
					const blockReason = validateDevRequest({
						origin: req.headers.origin,
						host: req.headers.host,
						"x-forwarded-host": req.headers["x-forwarded-host"],
						"sec-fetch-site": req.headers["sec-fetch-site"],
						"sec-fetch-mode": req.headers["sec-fetch-mode"]
					}, nextConfig?.allowedDevOrigins);
					if (blockReason) {
						console.warn(`[vinext] Blocked dev request: ${blockReason} (${req.url})`);
						res.writeHead(403, { "Content-Type": "text/plain" });
						res.end("Forbidden");
						return;
					}
					next();
				});
				return () => {
					if (instrumentationPath && !hasAppDir) runInstrumentation(getPagesRunner(), instrumentationPath).catch((err) => {
						console.error("[vinext] Instrumentation error:", err);
					});
					if (hasAppDir) server.middlewares.use((req, res, next) => {
						const url = req.url ?? "/";
						const [pathname] = url.split("?");
						if (url.startsWith("/@") || url.startsWith("/__vite") || url.startsWith("/node_modules") || url.includes(".") && !pathname.endsWith(".html") && !pathname.endsWith(".rsc")) return next();
						const _reqStart = now();
						let _compileMs;
						let _renderMs;
						function _parseTiming(raw) {
							const [handlerStart, inHandlerCompileMs, renderMs] = String(raw).split(",").map((v) => Number(v));
							if (!Number.isNaN(handlerStart) && !Number.isNaN(inHandlerCompileMs) && inHandlerCompileMs !== -1) _compileMs = Math.max(0, Math.round(handlerStart - _reqStart)) + inHandlerCompileMs;
							if (!Number.isNaN(renderMs) && renderMs !== -1) _renderMs = renderMs;
						}
						const _origSetHeader = res.setHeader.bind(res);
						res.setHeader = function(name, value) {
							if (name.toLowerCase() === "x-vinext-timing") {
								_parseTiming(value);
								return res;
							}
							return _origSetHeader(name, value);
						};
						const _origWriteHead = res.writeHead.bind(res);
						res.writeHead = function(statusCode, ...args) {
							let headers;
							const [reasonOrHeaders, maybeHeaders] = args;
							if (typeof reasonOrHeaders === "string") headers = maybeHeaders;
							else headers = reasonOrHeaders;
							if (headers && typeof headers === "object" && !Array.isArray(headers)) {
								const timingKey = Object.keys(headers).find((k) => k.toLowerCase() === VINEXT_TIMING_HEADER);
								if (timingKey) {
									_parseTiming(headers[timingKey]);
									delete headers[timingKey];
								}
							}
							return _origWriteHead(statusCode, ...args);
						};
						res.on("finish", () => {
							const logUrl = url.replace(/\.rsc(\?|$)/, "$1");
							const totalMs = now() - _reqStart;
							const resolvedRenderMs = _renderMs !== void 0 ? _renderMs : _compileMs !== void 0 ? Math.max(0, Math.round(totalMs - _compileMs)) : void 0;
							logRequest({
								method: req.method ?? "GET",
								url: logUrl,
								status: res.statusCode,
								totalMs,
								compileMs: _compileMs,
								renderMs: resolvedRenderMs
							});
						});
						next();
					});
					const handlePagesMiddleware = async (req, res, next) => {
						try {
							let url = req.url ?? "/";
							if (!hasPagesDir) return next();
							if (url.startsWith("/@") || url.startsWith("/__vite") || url.startsWith("/node_modules")) return next();
							if (url.split("?")[0].endsWith(".rsc")) return next();
							const blockReason = validateDevRequest({
								origin: req.headers.origin,
								host: req.headers.host,
								"x-forwarded-host": req.headers["x-forwarded-host"],
								"sec-fetch-site": req.headers["sec-fetch-site"],
								"sec-fetch-mode": req.headers["sec-fetch-mode"]
							}, nextConfig?.allowedDevOrigins);
							if (blockReason) {
								console.warn(`[vinext] Blocked dev request: ${blockReason} (${url})`);
								res.writeHead(403, { "Content-Type": "text/plain" });
								res.end("Forbidden");
								return;
							}
							if (url.split("?")[0] === "/_vinext/image") {
								const rawImgUrl = new URLSearchParams(url.split("?")[1] ?? "").get("url");
								const imgUrl = rawImgUrl?.replaceAll("\\", "/") ?? null;
								if (!imgUrl || !imgUrl.startsWith("/") || imgUrl.startsWith("//") || imgUrl.startsWith("/@") || imgUrl.startsWith("/__vite") || imgUrl.startsWith("/node_modules")) {
									res.writeHead(400);
									res.end(!rawImgUrl ? "Missing url parameter" : "Only relative URLs allowed");
									return;
								}
								const resolvedImg = new URL(imgUrl, `http://${req.headers.host || "localhost"}`);
								if (resolvedImg.origin !== `http://${req.headers.host || "localhost"}`) {
									res.writeHead(400);
									res.end("Only relative URLs allowed");
									return;
								}
								const encodedLocation = resolvedImg.pathname + resolvedImg.search;
								res.writeHead(302, { Location: encodedLocation });
								res.end();
								return;
							}
							const rawPathname = url.split("?")[0];
							if (rawPathname.endsWith("/index.html")) url = url.replace("/index.html", "/");
							else if (rawPathname.endsWith(".html")) url = url.replace(/\.html(?=\?|$)/, "");
							let pathname = url.split("?")[0];
							if (pathname.includes(".") && !pathname.endsWith(".html")) return next();
							if (isOpenRedirectShaped(pathname)) {
								res.writeHead(404);
								res.end("404 Not Found");
								return;
							}
							pathname = pathname.replaceAll("\\", "/");
							try {
								pathname = normalizePath$1(normalizePathnameForRouteMatchStrict(pathname));
							} catch {
								res.writeHead(400);
								res.end("Bad Request");
								return;
							}
							const bp = nextConfig?.basePath ?? "";
							if (bp && pathname.startsWith(bp)) {
								const stripped = pathname.slice(bp.length) || "/";
								url = stripped + (url.includes("?") ? url.slice(url.indexOf("?")) : "");
								pathname = stripped;
							}
							if (nextConfig && pathname !== "/" && pathname !== "/api" && !pathname.startsWith("/api/")) {
								const hasTrailing = pathname.endsWith("/");
								if (nextConfig.trailingSlash && !hasTrailing) {
									const qs = url.includes("?") ? url.slice(url.indexOf("?")) : "";
									const dest = bp + pathname + "/" + qs;
									res.writeHead(308, { Location: dest });
									res.end();
									return;
								} else if (!nextConfig.trailingSlash && hasTrailing) {
									const qs = url.includes("?") ? url.slice(url.indexOf("?")) : "";
									const dest = bp + removeTrailingSlash(pathname) + qs;
									res.writeHead(308, { Location: dest });
									res.end();
									return;
								}
							}
							if (hasCloudflarePlugin) return next();
							const nodeRequestHeaders = filterInternalHeaders(new Headers(Object.fromEntries(Object.entries(req.headers).filter(([, v]) => v !== void 0).map(([k, v]) => [k, Array.isArray(v) ? v.join(", ") : String(v)]))));
							for (const header of INTERNAL_HEADERS) delete req.headers[header];
							const requestOrigin = `http://${req.headers.host || "localhost"}`;
							const preMiddlewareReqUrl = new URL(url, requestOrigin);
							const preMiddlewareReqCtx = requestContextFromRequest(new Request(preMiddlewareReqUrl, { headers: nodeRequestHeaders }));
							if (nextConfig?.redirects.length) {
								if (applyRedirects(pathname, res, nextConfig.redirects, preMiddlewareReqCtx, nextConfig.basePath ?? "")) return;
							}
							const applyRequestHeadersToNodeRequest = (nextRequestHeaders) => {
								for (const key of Object.keys(req.headers)) delete req.headers[key];
								for (const [key, value] of nextRequestHeaders) req.headers[key] = value;
							};
							let middlewareRequestHeaders = null;
							let deferredMwResponseHeaders = null;
							const applyDeferredMwHeaders = () => {
								if (deferredMwResponseHeaders) for (const [key, value] of deferredMwResponseHeaders) res.appendHeader(key, value);
							};
							const applyMwRequestHeadersForExternalProxy = () => {
								if (middlewareRequestHeaders) applyRequestHeadersToNodeRequest(middlewareRequestHeaders);
								else delete req.headers[VINEXT_MW_CTX_HEADER];
							};
							if (middlewarePath) {
								const rawProto = process.env.VINEXT_TRUST_PROXY === "1" || (process.env.VINEXT_TRUSTED_HOSTS ?? "").split(",").some((h) => h.trim()) ? String(req.headers["x-forwarded-proto"] || "").split(",")[0].trim() : "";
								const origin = `${rawProto === "https" || rawProto === "http" ? rawProto : "http"}://${req.headers.host || "localhost"}`;
								const middlewareRequest = new Request(new URL(url, origin), {
									method: req.method,
									headers: nodeRequestHeaders
								});
								const result = await runMiddleware(getPagesRunner(), middlewarePath, middlewareRequest, nextConfig?.i18n, nextConfig?.basePath);
								if (result.waitUntilPromises?.length) Promise.allSettled(result.waitUntilPromises);
								if (!result.continue) {
									if (result.redirectUrl) {
										const redirectHeaders = { Location: result.redirectUrl };
										if (result.responseHeaders) for (const [key, value] of result.responseHeaders) {
											const existing = redirectHeaders[key];
											if (existing === void 0) redirectHeaders[key] = value;
											else if (Array.isArray(existing)) existing.push(value);
											else redirectHeaders[key] = [existing, value];
										}
										res.writeHead(result.redirectStatus ?? 307, redirectHeaders);
										res.end();
										return;
									}
									if (result.response) {
										res.statusCode = result.response.status;
										for (const [key, value] of result.response.headers) res.appendHeader(key, value);
										const body = Buffer.from(await result.response.arrayBuffer());
										res.end(body);
										return;
									}
								}
								if (result.responseHeaders) {
									const currentRequestHeaders = new Headers();
									for (const [key, value] of Object.entries(req.headers)) if (Array.isArray(value)) currentRequestHeaders.set(key, value.join(", "));
									else if (value !== void 0) currentRequestHeaders.set(key, value);
									middlewareRequestHeaders = buildRequestHeadersFromMiddlewareResponse(currentRequestHeaders, result.responseHeaders, { preserveCredentialHeaders: Boolean(result.rewriteUrl && isExternalUrl(result.rewriteUrl)) });
									if (middlewareRequestHeaders && !hasAppDir) applyRequestHeadersToNodeRequest(middlewareRequestHeaders);
									if (hasAppDir) {
										deferredMwResponseHeaders = [];
										for (const [key, value] of result.responseHeaders) if (!key.startsWith("x-middleware-")) deferredMwResponseHeaders.push([key, value]);
									} else for (const [key, value] of result.responseHeaders) if (!key.startsWith("x-middleware-")) res.appendHeader(key, value);
								}
								if (result.rewriteUrl) {
									url = result.rewriteUrl;
									req.url = url;
								}
								const middlewareStatus = result.status ?? result.rewriteStatus;
								if (middlewareStatus !== void 0) req.__vinextMiddlewareStatus = middlewareStatus;
								if (hasAppDir) {
									const mwCtxEntries = [];
									if (result.responseHeaders) {
										for (const [key, value] of result.responseHeaders) if (key !== "x-middleware-next" && key !== "x-middleware-rewrite") mwCtxEntries.push([key, value]);
									}
									req.headers[VINEXT_MW_CTX_HEADER] = JSON.stringify({
										h: mwCtxEntries,
										s: middlewareStatus ?? null,
										r: result.rewriteUrl ?? null
									});
								}
							}
							const reqUrl = new URL(url, requestOrigin);
							const reqCtx = requestContextFromRequest(new Request(reqUrl, { headers: middlewareRequestHeaders ?? nodeRequestHeaders }));
							if (nextConfig?.headers.length) applyHeaders(pathname, res, nextConfig.headers, preMiddlewareReqCtx);
							let resolvedUrl = url;
							if (nextConfig?.rewrites.beforeFiles.length) resolvedUrl = applyRewrites(pathname, nextConfig.rewrites.beforeFiles, reqCtx) ?? url;
							if (isExternalUrl(resolvedUrl)) {
								applyDeferredMwHeaders();
								applyMwRequestHeadersForExternalProxy();
								await proxyExternalRewriteNode(req, res, resolvedUrl);
								return;
							}
							const resolvedPathname = resolvedUrl.split("?")[0];
							if (resolvedPathname.startsWith("/api/") || resolvedPathname === "/api") {
								const apiRoutes = await apiRouter(pagesDir, nextConfig?.pageExtensions, fileMatcher);
								if (matchRoute(resolvedUrl, apiRoutes)) {
									applyDeferredMwHeaders();
									if (middlewareRequestHeaders) applyRequestHeadersToNodeRequest(middlewareRequestHeaders);
								}
								if (await handleApiRoute(getPagesRunner(), req, res, resolvedUrl, apiRoutes)) return;
								if (hasAppDir) return next();
								res.statusCode = 404;
								res.end("404 - API route not found");
								return;
							}
							const routes = await pagesRouter(pagesDir, nextConfig?.pageExtensions, fileMatcher);
							let match = matchRoute(resolvedUrl.split("?")[0], routes);
							if ((!match || match.route.isDynamic) && nextConfig?.rewrites.afterFiles.length) {
								const afterRewrite = applyRewrites(resolvedUrl.split("?")[0], nextConfig.rewrites.afterFiles, reqCtx);
								if (afterRewrite) {
									resolvedUrl = afterRewrite;
									match = matchRoute(resolvedUrl.split("?")[0], routes);
								}
							}
							if (isExternalUrl(resolvedUrl)) {
								applyDeferredMwHeaders();
								applyMwRequestHeadersForExternalProxy();
								await proxyExternalRewriteNode(req, res, resolvedUrl);
								return;
							}
							const handler = createSSRHandler(server, getPagesRunner(), routes, pagesDir, nextConfig?.i18n, fileMatcher, nextConfig?.basePath ?? "", nextConfig?.trailingSlash ?? false);
							const mwStatus = req.__vinextMiddlewareStatus;
							if (match) {
								applyDeferredMwHeaders();
								if (middlewareRequestHeaders) applyRequestHeadersToNodeRequest(middlewareRequestHeaders);
								await handler(req, res, resolvedUrl, mwStatus);
								return;
							}
							if (nextConfig?.rewrites.fallback.length) {
								const fallbackRewrite = applyRewrites(resolvedUrl.split("?")[0], nextConfig.rewrites.fallback, reqCtx);
								if (fallbackRewrite) {
									if (isExternalUrl(fallbackRewrite)) {
										applyDeferredMwHeaders();
										applyMwRequestHeadersForExternalProxy();
										await proxyExternalRewriteNode(req, res, fallbackRewrite);
										return;
									}
									if (!matchRoute(fallbackRewrite.split("?")[0], routes) && hasAppDir) return next();
									applyDeferredMwHeaders();
									if (middlewareRequestHeaders) applyRequestHeadersToNodeRequest(middlewareRequestHeaders);
									await handler(req, res, fallbackRewrite, mwStatus);
									return;
								}
							}
							if (hasAppDir) return next();
							await handler(req, res, resolvedUrl, mwStatus);
						} catch (e) {
							next(e);
						}
					};
					server.middlewares.use((req, res, next) => {
						handlePagesMiddleware(req, res, next);
					});
				};
			}
		},
		{
			name: "vinext:strip-server-exports",
			transform: {
				filter: { id: /\.(tsx?|jsx?|mjs)$/ },
				handler(code, id) {
					if (this.environment?.name !== "client") return null;
					if (!hasPagesDir) return null;
					if (!id.startsWith(pagesDir)) return null;
					const relativePath = id.slice(pagesDir.length);
					if (relativePath.startsWith("/api/") || relativePath === "/api") return null;
					if (/\/_(?:app|document|error)\b/.test(relativePath)) return null;
					const result = stripServerExports(code);
					if (!result) return null;
					return {
						code: result,
						map: null
					};
				}
			}
		},
		{
			name: "vinext:image-imports",
			enforce: "pre",
			_dimCache: imageImportDimCache,
			resolveId: {
				filter: { id: /\?vinext-meta$/ },
				handler(source, _importer) {
					if (!source.endsWith("?vinext-meta")) return null;
					return `\0vinext-image-meta:${source.replace("?vinext-meta", "")}`;
				}
			},
			async load(id) {
				if (!id.startsWith("\0vinext-image-meta:")) return null;
				const imagePath = id.replace("\0vinext-image-meta:", "");
				const cache = imageImportDimCache;
				let dims = cache.get(imagePath);
				if (!dims) try {
					const { imageSize } = await import("image-size");
					const result = imageSize(fs.readFileSync(imagePath));
					dims = {
						width: result.width ?? 0,
						height: result.height ?? 0
					};
					cache.set(imagePath, dims);
				} catch {
					dims = {
						width: 0,
						height: 0
					};
				}
				return `export default ${JSON.stringify(dims)};`;
			},
			transform: {
				filter: {
					id: {
						include: /\.(tsx?|jsx?|mjs)$/,
						exclude: /node_modules/
					},
					code: new RegExp(`import\\s+\\w+\\s+from\\s+['"][^'"]+\\.(${IMAGE_EXTS})['"]`)
				},
				async handler(code, id) {
					if (id.includes("node_modules")) return null;
					if (id.startsWith("\0")) return null;
					if (!id.match(/\.(tsx?|jsx?|mjs)$/)) return null;
					const imageImportRe = new RegExp(`import\\s+(\\w+)\\s+from\\s+['"]([^'"]+\\.(${IMAGE_EXTS}))['"];?`, "g");
					if (!imageImportRe.test(code)) return null;
					imageImportRe.lastIndex = 0;
					const s = new MagicString(code);
					let hasChanges = false;
					let match;
					while ((match = imageImportRe.exec(code)) !== null) {
						const [fullMatch, varName, importPath] = match;
						const matchStart = match.index;
						const matchEnd = matchStart + fullMatch.length;
						const dir = path.dirname(id);
						const absImagePath = path.resolve(dir, importPath);
						if (!fs.existsSync(absImagePath)) continue;
						const urlVar = `__vinext_img_url_${varName}`;
						const metaVar = `__vinext_img_meta_${varName}`;
						const replacement = `import ${urlVar} from ${JSON.stringify(importPath)};\nimport ${metaVar} from ${JSON.stringify(absImagePath + "?vinext-meta")};\nconst ${varName} = { src: ${urlVar}, width: ${metaVar}.width, height: ${metaVar}.height };`;
						s.overwrite(matchStart, matchEnd, replacement);
						hasChanges = true;
					}
					if (!hasChanges) return null;
					return {
						code: s.toString(),
						map: s.generateMap({ hires: "boundary" })
					};
				}
			}
		},
		createGoogleFontsPlugin(_fontGoogleShimPath, _shimsDir),
		createLocalFontsPlugin(),
		createOptimizeImportsPlugin(() => nextConfig, () => root),
		{
			name: "vinext:use-cache",
			transform: {
				filter: {
					id: {
						include: /\.(tsx?|jsx?|mjs)$/,
						exclude: /node_modules/
					},
					code: "use cache"
				},
				async handler(code, id) {
					if (id.includes("node_modules")) return null;
					if (id.startsWith("\0")) return null;
					if (!id.match(/\.(tsx?|jsx?|mjs)$/)) return null;
					if (!code.includes("use cache")) return null;
					const ast = parseAst(code);
					const cacheDirective = ast.body.find((node) => node.type === "ExpressionStatement" && node.expression?.type === "Literal" && typeof node.expression.value === "string" && node.expression.value.startsWith("use cache"));
					function nodeHasInlineCacheDirective(node) {
						if (!node || typeof node !== "object") return false;
						const fn = node.type === "MethodDefinition" ? node.value : node;
						const stmts = fn?.body?.type === "BlockStatement" ? fn.body.body : null;
						if (Array.isArray(stmts)) {
							for (const stmt of stmts) if (stmt?.type === "ExpressionStatement" && stmt.expression?.type === "Literal" && typeof stmt.expression?.value === "string" && /^use cache(:\s*\w+)?$/.test(stmt.expression.value)) return true;
						}
						return false;
					}
					function astHasInlineCache(nodes) {
						for (const node of nodes) {
							if (!node || typeof node !== "object") continue;
							if ((node.type === "FunctionDeclaration" || node.type === "FunctionExpression" || node.type === "ArrowFunctionExpression" || node.type === "MethodDefinition") && nodeHasInlineCacheDirective(node)) return true;
							for (const key of Object.keys(node)) {
								if (key === "type" || key === "start" || key === "end" || key === "loc") continue;
								const child = node[key];
								if (Array.isArray(child) && child.some((c) => c && typeof c === "object")) {
									if (astHasInlineCache(child)) return true;
								} else if (child && typeof child === "object" && child.type) {
									if (astHasInlineCache([child])) return true;
								}
							}
						}
						return false;
					}
					const hasInlineCache = !cacheDirective && astHasInlineCache(ast.body);
					if (!cacheDirective && !hasInlineCache) return null;
					if (!resolvedRscTransformsPath) throw new Error("vinext: 'use cache' requires @vitejs/plugin-rsc to be installed.\nRun: " + detectPackageManager(process.cwd()) + " @vitejs/plugin-rsc");
					const { transformWrapExport, transformHoistInlineDirective } = await import(pathToFileURL(resolvedRscTransformsPath).href);
					if (cacheDirective) {
						const directiveValue = cacheDirective.expression.value;
						const variant = directiveValue === "use cache" ? "" : directiveValue.replace("use cache:", "").replace("use cache: ", "").trim();
						const isLayoutOrTemplate = /\/(layout|template)\.(tsx?|jsx?|mjs)$/.test(id);
						const runtimeModuleUrl = pathToFileURL(resolveShimModulePath(shimsDir, "cache-runtime")).href;
						const result = transformWrapExport(code, ast, {
							runtime: (value, name) => `(await import(${JSON.stringify(runtimeModuleUrl)})).registerCachedFunction(${value}, ${JSON.stringify(id + ":" + name)}, ${JSON.stringify(variant)})`,
							rejectNonAsyncFunction: false,
							filter: (name, meta) => {
								if (meta.isFunction === false) return false;
								if (isLayoutOrTemplate && name === "default") return false;
								return true;
							}
						});
						if (result.exportNames.length > 0) {
							const output = result.output;
							output.overwrite(cacheDirective.start, cacheDirective.end, `/* "use cache" — wrapped by vinext */`);
							return {
								code: output.toString(),
								map: output.generateMap({ hires: "boundary" })
							};
						}
						const output = new MagicString(code);
						output.overwrite(cacheDirective.start, cacheDirective.end, `/* "use cache" — handled by vinext */`);
						return {
							code: output.toString(),
							map: output.generateMap({ hires: "boundary" })
						};
					}
					if (hasInlineCache) {
						const runtimeModuleUrl2 = pathToFileURL(resolveShimModulePath(shimsDir, "cache-runtime")).href;
						try {
							const result = transformHoistInlineDirective(code, ast, {
								directive: /^use cache(:\s*\w+)?$/,
								runtime: (value, name, meta) => {
									const directiveMatch = meta.directiveMatch[0];
									const variant = directiveMatch === "use cache" ? "" : directiveMatch.replace("use cache:", "").replace("use cache: ", "").trim();
									return `(await import(${JSON.stringify(runtimeModuleUrl2)})).registerCachedFunction(${value}, ${JSON.stringify(id + ":" + name)}, ${JSON.stringify(variant)})`;
								},
								rejectNonAsyncFunction: false
							});
							if (result.names.length > 0) return {
								code: result.output.toString(),
								map: result.output.generateMap({ hires: "boundary" })
							};
						} catch {}
					}
					return null;
				}
			}
		},
		createOgInlineFetchAssetsPlugin(),
		ogAssetsPlugin,
		createServerExternalsManifestPlugin(),
		{
			name: "vinext:image-config",
			apply: "build",
			enforce: "post",
			writeBundle: {
				sequential: true,
				order: "post",
				handler(options) {
					if (this.environment?.name !== "rsc") return;
					const outDir = options.dir;
					if (!outDir) return;
					const imageConfig = {
						dangerouslyAllowSVG: nextConfig?.images?.dangerouslyAllowSVG,
						contentDispositionType: nextConfig?.images?.contentDispositionType,
						contentSecurityPolicy: nextConfig?.images?.contentSecurityPolicy
					};
					fs.writeFileSync(path.join(outDir, "image-config.json"), JSON.stringify(imageConfig));
				}
			}
		},
		(() => {
			let buildIdWritten = false;
			return {
				name: "vinext:build-id",
				apply: "build",
				enforce: "post",
				closeBundle: {
					sequential: true,
					order: "post",
					handler() {
						if (buildIdWritten) return;
						buildIdWritten = true;
						const outDir = path.join(root, "dist", "server");
						fs.mkdirSync(outDir, { recursive: true });
						fs.writeFileSync(path.join(outDir, "BUILD_ID"), nextConfig.buildId);
					}
				}
			};
		})(),
		{
			name: "vinext:hash-salt",
			apply: "build",
			augmentChunkHash() {
				if (this.environment?.name !== "client") return;
				const salt = nextConfig?.hashSalt;
				if (salt) return salt;
			}
		},
		(() => {
			const prerenderSecret = randomBytes(32).toString("hex");
			return {
				name: "vinext:server-manifest",
				apply: "build",
				enforce: "post",
				writeBundle: {
					sequential: true,
					order: "post",
					handler(options) {
						const envName = this.environment?.name;
						if (envName !== "rsc" && envName !== "ssr") return;
						const outDir = options.dir;
						if (!outDir) return;
						const manifest = { prerenderSecret };
						fs.writeFileSync(path.join(outDir, "vinext-server.json"), JSON.stringify(manifest));
					}
				}
			};
		})(),
		{
			name: "vinext:nitro-route-rules",
			nitro: { setup: async (nitro) => {
				if (nitro.options.dev) return;
				if (!nextConfig) return;
				if (!hasAppDir && !hasPagesDir) return;
				const { collectNitroRouteRules, mergeNitroRouteRules } = await import("./build/nitro-route-rules.js");
				const generatedRouteRules = await collectNitroRouteRules({
					appDir: hasAppDir ? appDir : null,
					pagesDir: hasPagesDir ? pagesDir : null,
					pageExtensions: nextConfig.pageExtensions
				});
				if (Object.keys(generatedRouteRules).length === 0) return;
				const { routeRules, skippedRoutes } = mergeNitroRouteRules(nitro.options.routeRules, generatedRouteRules);
				nitro.options.routeRules = routeRules;
				if (skippedRoutes.length > 0) (nitro.logger?.warn ?? console.warn)(`[vinext] Skipping generated Nitro routeRules for routes with existing exact cache config: ${skippedRoutes.join(", ")}`);
			} }
		},
		{
			name: "vinext:ssr-manifest-backfill",
			apply: "build",
			enforce: "post",
			writeBundle: {
				sequential: true,
				order: "post",
				handler(options, bundle) {
					const outDir = options.dir;
					if (!outDir) return;
					const viteDir = path.join(outDir, ".vite");
					const ssrManifestPath = path.join(viteDir, "ssr-manifest.json");
					if (!fs.existsSync(ssrManifestPath)) return;
					try {
						const augmentedManifest = augmentSsrManifestFromBundle(JSON.parse(fs.readFileSync(ssrManifestPath, "utf-8")), bundle, this.environment?.config.root ?? process.cwd(), this.environment?.config.base ?? "/");
						fs.writeFileSync(ssrManifestPath, JSON.stringify(augmentedManifest, null, 2));
					} catch (err) {
						console.warn("[vinext] Failed to augment SSR manifest:", err);
					}
				}
			}
		},
		(() => {
			let pendingPrecompress = null;
			let pendingPrecompressError = null;
			return {
				name: "vinext:precompress",
				apply: "build",
				enforce: "post",
				writeBundle: {
					sequential: true,
					order: "post",
					handler(outputOptions) {
						if (this.environment?.name !== "client") return;
						if (!options.precompress && process.env.VINEXT_PRECOMPRESS !== "1") return;
						const outDir = outputOptions.dir;
						if (!outDir) return;
						const assetsDir = path.join(outDir, "assets");
						if (!fs.existsSync(assetsDir)) return;
						const isTTY = process.stderr.isTTY;
						let lastLineLen = 0;
						pendingPrecompressError = null;
						pendingPrecompress = (async () => {
							const result = await precompressAssets(outDir, (completed, total, file) => {
								if (!isTTY) return;
								const pct = total > 0 ? Math.floor(completed / total * 100) : 0;
								const bar = `[${"█".repeat(Math.floor(pct / 5))}${" ".repeat(20 - Math.floor(pct / 5))}]`;
								const maxFile = 30;
								const fileLabel = file.length > maxFile ? "…" + file.slice(-(maxFile - 1)) : file;
								const line = `Compressing assets... ${bar} ${String(completed).padStart(String(total).length)}/${total} ${fileLabel}`;
								const padded = line.padEnd(lastLineLen);
								lastLineLen = line.length;
								process.stderr.write(`\r${padded}`);
							});
							if (isTTY) process.stderr.write(`\r${" ".repeat(lastLineLen)}\r`);
							if (result.filesCompressed > 0) {
								const ratio = ((1 - result.totalBrotliBytes / result.totalOriginalBytes) * 100).toFixed(1);
								console.log(`  Precompressed ${result.filesCompressed} assets (${ratio}% smaller with brotli)`);
							}
						})().catch((error) => {
							pendingPrecompressError = error;
							console.error("[vinext] Precompression failed:", error);
						});
					}
				},
				closeBundle: {
					sequential: true,
					order: "post",
					async handler() {
						if (this.environment?.name !== "ssr") return;
						if (!pendingPrecompress) return;
						const task = pendingPrecompress;
						pendingPrecompress = null;
						await task;
						if (pendingPrecompressError) {
							const error = pendingPrecompressError;
							pendingPrecompressError = null;
							throw error;
						}
					}
				}
			};
		})(),
		{
			name: "vinext:cloudflare-build",
			apply: "build",
			enforce: "post",
			closeBundle: {
				sequential: true,
				order: "post",
				async handler() {
					const envName = this.environment?.name;
					if (!envName || !hasCloudflarePlugin) return;
					if (envName !== "client") return;
					const envConfig = this.environment?.config;
					if (!envConfig) return;
					const buildRoot = envConfig.root ?? process.cwd();
					const distDir = path.resolve(buildRoot, "dist");
					if (!fs.existsSync(distDir)) return;
					const clientDir = path.resolve(buildRoot, "dist", "client");
					const clientBase = envConfig.base ?? "/";
					let lazyChunksData = null;
					let clientEntryFile = null;
					const buildManifestPath = path.join(clientDir, ".vite", "manifest.json");
					if (fs.existsSync(buildManifestPath)) try {
						const buildManifest = JSON.parse(fs.readFileSync(buildManifestPath, "utf-8"));
						for (const [, value] of Object.entries(buildManifest)) if (value && value.isEntry && value.file) {
							clientEntryFile = manifestFileWithBase(value.file, clientBase);
							break;
						}
						const lazy = manifestFilesWithBase(computeLazyChunks(buildManifest), clientBase);
						if (lazy.length > 0) lazyChunksData = lazy;
					} catch {}
					let ssrManifestData = null;
					const ssrManifestPath = path.join(clientDir, ".vite", "ssr-manifest.json");
					if (fs.existsSync(ssrManifestPath)) try {
						ssrManifestData = JSON.parse(fs.readFileSync(ssrManifestPath, "utf-8"));
					} catch {}
					if (hasAppDir) {
						const workerEntry = path.resolve(distDir, "server", "index.js");
						if (fs.existsSync(workerEntry) && (lazyChunksData || ssrManifestData)) {
							let code = fs.readFileSync(workerEntry, "utf-8");
							const globals = [];
							if (ssrManifestData) globals.push(`globalThis.__VINEXT_SSR_MANIFEST__ = ${JSON.stringify(ssrManifestData)};`);
							if (lazyChunksData) globals.push(`globalThis.__VINEXT_LAZY_CHUNKS__ = ${JSON.stringify(lazyChunksData)};`);
							code = globals.join("\n") + "\n" + code;
							fs.writeFileSync(workerEntry, code);
						}
					} else {
						let workerOutDir = null;
						for (const entry of fs.readdirSync(distDir)) {
							const candidate = path.join(distDir, entry);
							if (entry === "client") continue;
							if (fs.statSync(candidate).isDirectory() && fs.existsSync(path.join(candidate, "wrangler.json"))) {
								workerOutDir = candidate;
								break;
							}
						}
						if (!workerOutDir) return;
						const workerEntry = path.join(workerOutDir, "index.js");
						if (!fs.existsSync(workerEntry)) return;
						if (!clientEntryFile) {
							const assetsDir = path.join(clientDir, "assets");
							if (fs.existsSync(assetsDir)) {
								const entry = fs.readdirSync(assetsDir).find((f) => (f.includes("vinext-client-entry") || f.includes("vinext-app-browser-entry")) && f.endsWith(".js"));
								if (entry) clientEntryFile = manifestFileWithBase("assets/" + entry, clientBase);
							}
						}
						if (clientEntryFile || ssrManifestData || lazyChunksData) {
							let code = fs.readFileSync(workerEntry, "utf-8");
							const globals = [];
							if (clientEntryFile) globals.push(`globalThis.__VINEXT_CLIENT_ENTRY__ = ${JSON.stringify(clientEntryFile)};`);
							if (ssrManifestData) globals.push(`globalThis.__VINEXT_SSR_MANIFEST__ = ${JSON.stringify(ssrManifestData)};`);
							if (lazyChunksData) globals.push(`globalThis.__VINEXT_LAZY_CHUNKS__ = ${JSON.stringify(lazyChunksData)};`);
							code = globals.join("\n") + "\n" + code;
							fs.writeFileSync(workerEntry, code);
						}
					}
					const headersPath = path.join(clientDir, "_headers");
					if (!fs.existsSync(headersPath)) {
						const headersContent = [
							"# Cache content-hashed assets immutably (generated by vinext)",
							`/${envConfig.build?.assetsDir ?? "assets"}/*`,
							"  Cache-Control: public, max-age=31536000, immutable",
							""
						].join("\n");
						fs.mkdirSync(clientDir, { recursive: true });
						fs.writeFileSync(headersPath, headersContent);
					}
				}
			}
		},
		{
			name: "vinext:og-font-patch",
			enforce: "pre",
			transform(code, id) {
				if (!id.includes("@vercel/og") || !id.includes("index.edge.js")) return null;
				let result = code;
				const yogaMatch = /H = "data:application\/octet-stream;base64,([A-Za-z0-9+/]+=*)";/.exec(result);
				if (yogaMatch) {
					const yogaBase64 = yogaMatch[1];
					const distDir = path.dirname(id);
					const yogaWasmPath = path.join(distDir, "yoga.wasm");
					if (!fs.existsSync(yogaWasmPath)) fs.writeFileSync(yogaWasmPath, Buffer.from(yogaBase64, "base64"));
					result = result.replace(yogaMatch[0], `H = "";`);
					const YOGA_CALL = `yoga_wasm_base64_esm_default()`;
					const YOGA_CALL_PATCHED = [
						`yoga_wasm_base64_esm_default({ instantiateWasm: function(imports, callback) {`,
						`  __vi_yoga_mod.then(function(mod) {`,
						`    if (mod) {`,
						`      WebAssembly.instantiate(mod, imports).then(function(inst) { callback(inst); });`,
						`    } else {`,
						`      var b = Buffer.from(__vi_yoga_b64, "base64");`,
						`      WebAssembly.instantiate(b, imports).then(function(r) { callback(r.instance); });`,
						`    }`,
						`  });`,
						`  return {};`,
						`} })`
					].join("\n");
					result = result.replace(YOGA_CALL, YOGA_CALL_PATCHED);
					result = [`var __vi_yoga_b64 = ${JSON.stringify(yogaBase64)};`, `var __vi_yoga_mod = import("./yoga.wasm?module").then(function(m) { return m.default; }).catch(function() { return null; });`].join("\n") + "\n" + result;
				}
				const resvgMatch = /import\s+resvg_wasm\s+from\s+["']\.\/resvg\.wasm\?module["']\s*;?/.exec(result);
				if (resvgMatch) {
					const resvgLoader = [
						`var resvg_wasm = import("./resvg.wasm?module").then(function(m) { return m.default; }).catch(function() {`,
						`  return Promise.all([import("node:fs"), import("node:url")]).then(function(mods) {`,
						`    var p = mods[1].fileURLToPath(new URL("./resvg.wasm", import.meta.url));`,
						`    return mods[0].promises.readFile(p).then(function(buf) { return WebAssembly.compile(buf); });`,
						`  });`,
						`});`
					].join("\n");
					result = result.replace(resvgMatch[0], resvgLoader);
				}
				if (result === code) return null;
				return {
					code: result,
					map: null
				};
			}
		}
	];
	if (rscPluginPromise) {
		plugins.push(rscPluginPromise);
		plugins.push(createRscClientReferenceLoadersPlugin());
	}
	return plugins;
}
/**
* Collect all NEXT_PUBLIC_* env vars and create Vite define entries
* so they get inlined into the client bundle.
*/
function getNextPublicEnvDefines() {
	const defines = {};
	for (const [key, value] of Object.entries(process.env)) if (key.startsWith("NEXT_PUBLIC_") && value !== void 0) defines[`process.env.${key}`] = JSON.stringify(value);
	return defines;
}
/**
* Apply redirect rules from next.config.js.
* Returns true if a redirect was applied.
*/
function applyRedirects(pathname, res, redirects, ctx, basePath = "") {
	const result = matchRedirect(pathname, redirects, ctx);
	if (result) {
		const dest = sanitizeDestination(basePath && !isExternalUrl(result.destination) && !hasBasePath(result.destination, basePath) ? basePath + result.destination : result.destination);
		res.writeHead(result.permanent ? 308 : 307, { Location: dest });
		res.end();
		return true;
	}
	return false;
}
async function proxyExternalRewriteNode(req, res, externalUrl) {
	try {
		const origin = `http://${req.headers.host || "localhost"}`;
		const method = req.method ?? "GET";
		const hasBody = method !== "GET" && method !== "HEAD";
		const init = {
			method,
			headers: Object.fromEntries(Object.entries(req.headers).filter(([, v]) => v !== void 0).map(([k, v]) => [k, Array.isArray(v) ? v.join(", ") : String(v)]))
		};
		if (hasBody) {
			const { Readable } = await import("node:stream");
			init.body = Readable.toWeb(req);
			init.duplex = "half";
		}
		const proxyResponse = await proxyExternalRequest(new Request(new URL(req.url ?? "/", origin), init), externalUrl);
		const nodeHeaders = {};
		proxyResponse.headers.forEach((value, key) => {
			const existing = nodeHeaders[key];
			if (existing !== void 0) nodeHeaders[key] = Array.isArray(existing) ? [...existing, value] : [existing, value];
			else nodeHeaders[key] = value;
		});
		res.writeHead(proxyResponse.status, nodeHeaders);
		if (proxyResponse.body) {
			const { Readable: ReadableImport } = await import("node:stream");
			ReadableImport.fromWeb(proxyResponse.body).pipe(res);
		} else res.end();
	} catch (e) {
		console.error("[vinext] External rewrite proxy error:", e);
		if (!res.headersSent) {
			res.writeHead(502);
			res.end("Bad Gateway");
		}
	}
}
/**
* Apply rewrite rules from next.config.js.
* Returns the rewritten URL or null if no rewrite matched.
*/
function applyRewrites(pathname, rewrites, ctx) {
	const dest = matchRewrite(pathname, rewrites, ctx);
	if (dest) return sanitizeDestination(dest);
	return null;
}
/**
* Apply custom header rules from next.config.js.
* Middleware headers take precedence: if a header key was already set on the
* response (by middleware), the config value is skipped for that key.
*/
function applyHeaders(pathname, res, headers, ctx) {
	const matched = matchHeaders(pathname, headers, ctx);
	for (const header of matched) {
		const lk = header.key.toLowerCase();
		if (lk === "set-cookie") {
			const existing = res.getHeader(lk);
			if (Array.isArray(existing)) res.setHeader(header.key, [...existing, header.value]);
			else if (existing) res.setHeader(header.key, [String(existing), header.value]);
			else res.setHeader(header.key, header.value);
		} else if (lk === "vary") {
			const existing = res.getHeader(lk);
			if (existing) res.setHeader(header.key, existing + ", " + header.value);
			else res.setHeader(header.key, header.value);
		} else if (!res.getHeader(lk)) res.setHeader(header.key, header.value);
	}
}
/**
* Find a file by name (without extension) in a directory.
* Checks the configured page extensions.
*/
function findFileWithExts(dir, name, matcher) {
	for (const ext of matcher.dottedExtensions) {
		const filePath = path.join(dir, name + ext);
		if (fs.existsSync(filePath)) return filePath;
	}
	return null;
}
//#endregion
export { vinext as default, staticExportApp, staticExportPages };

//# sourceMappingURL=index.js.map