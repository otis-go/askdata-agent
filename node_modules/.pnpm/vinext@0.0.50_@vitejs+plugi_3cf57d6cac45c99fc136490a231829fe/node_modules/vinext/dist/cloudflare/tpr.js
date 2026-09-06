import { VINEXT_REVALIDATE_HEADER } from "../server/headers.js";
import { isrCacheKey } from "../server/isr-cache.js";
import { ENTRY_PREFIX } from "./kv-cache-handler.js";
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
//#region src/cloudflare/tpr.ts
/**
* TPR: Traffic-aware Pre-Rendering
*
* Uses Cloudflare zone analytics to determine which pages actually get
* traffic, and pre-renders only those during deploy. The pre-rendered
* HTML is uploaded to KV in the same format ISR uses at runtime — no
* runtime changes needed.
*
* Flow:
*   1. Parse wrangler config to find custom domain and KV namespace
*   2. Resolve the Cloudflare zone for the custom domain
*   3. Query zone analytics (GraphQL) for top pages by request count
*   4. Walk ranked list until coverage threshold is met
*   5. Start the built production server locally
*   6. Fetch each hot route to produce HTML
*   7. Upload pre-rendered HTML to KV (same KVCacheEntry format ISR reads)
*
* TPR is an experimental feature enabled via --experimental-tpr. It
* gracefully skips when no custom domain, no API token, no traffic data,
* or no KV namespace is configured.
*/
/**
* Parse wrangler config (JSONC or TOML) to extract the fields TPR needs:
* account_id, VINEXT_CACHE KV namespace ID, and custom domain.
*/
function parseWranglerConfig(root) {
	for (const filename of ["wrangler.jsonc", "wrangler.json"]) {
		const filepath = path.join(root, filename);
		if (fs.existsSync(filepath)) {
			const content = fs.readFileSync(filepath, "utf-8");
			try {
				return extractFromJSON(JSON.parse(stripJsonComments(content)));
			} catch {
				continue;
			}
		}
	}
	const tomlPath = path.join(root, "wrangler.toml");
	if (fs.existsSync(tomlPath)) return extractFromTOML(fs.readFileSync(tomlPath, "utf-8"));
	return null;
}
/**
* Strip single-line (//) and multi-line comments from JSONC while
* preserving strings that contain slashes.
*/
function stripJsonComments(str) {
	let result = "";
	let inString = false;
	let inSingleLine = false;
	let inMultiLine = false;
	let escapeNext = false;
	for (let i = 0; i < str.length; i++) {
		const ch = str[i];
		const next = str[i + 1];
		if (escapeNext) {
			if (!inSingleLine && !inMultiLine) result += ch;
			escapeNext = false;
			continue;
		}
		if (ch === "\\" && inString) {
			result += ch;
			escapeNext = true;
			continue;
		}
		if (inSingleLine) {
			if (ch === "\n") {
				inSingleLine = false;
				result += ch;
			}
			continue;
		}
		if (inMultiLine) {
			if (ch === "*" && next === "/") {
				inMultiLine = false;
				i++;
			}
			continue;
		}
		if (ch === "\"" && !inString) {
			inString = true;
			result += ch;
			continue;
		}
		if (ch === "\"" && inString) {
			inString = false;
			result += ch;
			continue;
		}
		if (!inString && ch === "/" && next === "/") {
			inSingleLine = true;
			i++;
			continue;
		}
		if (!inString && ch === "/" && next === "*") {
			inMultiLine = true;
			i++;
			continue;
		}
		result += ch;
	}
	return result;
}
function extractFromJSON(config) {
	const result = {};
	if (typeof config.account_id === "string") result.accountId = config.account_id;
	if (Array.isArray(config.kv_namespaces)) {
		const vinextKV = config.kv_namespaces.find((ns) => ns && typeof ns === "object" && ns.binding === "VINEXT_CACHE");
		if (vinextKV && typeof vinextKV.id === "string" && vinextKV.id !== "<your-kv-namespace-id>") result.kvNamespaceId = vinextKV.id;
	}
	const domain = extractDomainFromRoutes(config.routes) ?? extractDomainFromCustomDomains(config);
	if (domain) result.customDomain = domain;
	return result;
}
function extractDomainFromRoutes(routes) {
	if (!Array.isArray(routes)) return null;
	for (const route of routes) if (typeof route === "string") {
		const domain = cleanDomain(route);
		if (domain && !domain.includes("workers.dev")) return domain;
	} else if (route && typeof route === "object") {
		const r = route;
		const pattern = typeof r.zone_name === "string" ? r.zone_name : typeof r.pattern === "string" ? r.pattern : null;
		if (pattern) {
			const domain = cleanDomain(pattern);
			if (domain && !domain.includes("workers.dev")) return domain;
		}
	}
	return null;
}
function extractDomainFromCustomDomains(config) {
	if (Array.isArray(config.custom_domains)) {
		for (const d of config.custom_domains) if (typeof d === "string" && !d.includes("workers.dev")) return cleanDomain(d);
	}
	return null;
}
/** Strip protocol and trailing wildcards from a route pattern to get a bare domain. */
function cleanDomain(raw) {
	return raw.replace(/^https?:\/\//, "").replace(/\/\*$/, "").replace(/\/+$/, "").split("/")[0] || null;
}
/**
* Simple extraction of specific fields from wrangler.toml content.
* Not a full TOML parser — just enough for the fields we need.
*/
function extractFromTOML(content) {
	const result = {};
	const accountMatch = content.match(/^account_id\s*=\s*"([^"]+)"/m);
	if (accountMatch) result.accountId = accountMatch[1];
	const kvBlocks = content.split(/\[\[kv_namespaces\]\]/);
	for (let i = 1; i < kvBlocks.length; i++) {
		const block = kvBlocks[i].split(/\[\[/)[0];
		const bindingMatch = block.match(/binding\s*=\s*"([^"]+)"/);
		const idMatch = block.match(/\bid\s*=\s*"([^"]+)"/);
		if (bindingMatch?.[1] === "VINEXT_CACHE" && idMatch?.[1] && idMatch[1] !== "<your-kv-namespace-id>") result.kvNamespaceId = idMatch[1];
	}
	const routeMatch = content.match(/^route\s*=\s*"([^"]+)"/m);
	if (routeMatch) {
		const domain = cleanDomain(routeMatch[1]);
		if (domain && !domain.includes("workers.dev")) result.customDomain = domain;
	}
	if (!result.customDomain) {
		const routeBlocks = content.split(/\[\[routes\]\]/);
		for (let i = 1; i < routeBlocks.length; i++) {
			const patternMatch = routeBlocks[i].split(/\[\[/)[0].match(/pattern\s*=\s*"([^"]+)"/);
			if (patternMatch) {
				const domain = cleanDomain(patternMatch[1]);
				if (domain && !domain.includes("workers.dev")) {
					result.customDomain = domain;
					break;
				}
			}
		}
	}
	return result;
}
/**
* Generate zone lookup candidates from shortest (2-part) to longest.
* Tries the most common case first (e.g., "example.com") and progressively
* adds labels for multi-part TLDs (e.g., "co.uk" → "example.co.uk").
*
* "shop.example.com"    → ["example.com", "shop.example.com"]
* "shop.example.co.uk"  → ["co.uk", "example.co.uk", "shop.example.co.uk"]
* "example.com"         → ["example.com"]
*/
function domainCandidates(domain) {
	const parts = domain.split(".");
	const candidates = [];
	for (let i = parts.length - 2; i >= 0; i--) candidates.push(parts.slice(i).join("."));
	return candidates;
}
/** Resolve zone ID from a domain name via the Cloudflare API. */
async function resolveZoneId(domain, apiToken) {
	for (const candidate of domainCandidates(domain)) {
		const response = await fetch(`https://api.cloudflare.com/client/v4/zones?name=${encodeURIComponent(candidate)}`, { headers: {
			Authorization: `Bearer ${apiToken}`,
			"Content-Type": "application/json"
		} });
		if (!response.ok) continue;
		const data = await response.json();
		if (data.success && data.result?.length) return data.result[0].id;
	}
	return null;
}
/** Resolve the account ID associated with the API token. */
async function resolveAccountId(apiToken) {
	const response = await fetch("https://api.cloudflare.com/client/v4/accounts?per_page=1", { headers: {
		Authorization: `Bearer ${apiToken}`,
		"Content-Type": "application/json"
	} });
	if (!response.ok) return null;
	const data = await response.json();
	if (!data.success || !data.result?.length) return null;
	return data.result[0].id;
}
/**
* Query Cloudflare zone analytics for top page paths by request count
* over the given time window.
*/
async function queryTraffic(zoneTag, apiToken, windowHours) {
	const now = /* @__PURE__ */ new Date();
	const query = `{
    viewer {
      zones(filter: { zoneTag: "${zoneTag}" }) {
        httpRequestsAdaptiveGroups(
          limit: 10000
          orderBy: [sum_requests_DESC]
          filter: {
            datetime_geq: "${(/* @__PURE__ */ new Date(now.getTime() - windowHours * 60 * 60 * 1e3)).toISOString()}"
            datetime_lt: "${now.toISOString()}"
            requestSource: "eyeball"
          }
        ) {
          sum { requests }
          dimensions { clientRequestPath }
        }
      }
    }
  }`;
	const response = await fetch("https://api.cloudflare.com/client/v4/graphql", {
		method: "POST",
		headers: {
			Authorization: `Bearer ${apiToken}`,
			"Content-Type": "application/json"
		},
		body: JSON.stringify({ query })
	});
	if (!response.ok) throw new Error(`Zone analytics query failed: ${response.status} ${response.statusText}`);
	const data = await response.json();
	if (data.errors?.length) throw new Error(`Zone analytics error: ${data.errors[0].message}`);
	const groups = data.data?.viewer?.zones?.[0]?.httpRequestsAdaptiveGroups;
	if (!groups || groups.length === 0) return [];
	return filterTrafficPaths(groups.map((g) => ({
		path: g.dimensions.clientRequestPath,
		requests: g.sum.requests
	})));
}
/** Filter out non-page requests (static assets, API routes, internal routes). */
function filterTrafficPaths(entries) {
	return entries.filter((e) => {
		if (!e.path.startsWith("/")) return false;
		if (/\.(js|css|png|jpg|jpeg|gif|svg|ico|woff2?|ttf|eot|map|webp|avif)$/i.test(e.path)) return false;
		if (e.path.startsWith("/api/")) return false;
		if (e.path.startsWith("/_vinext/") || e.path.startsWith("/_next/")) return false;
		if (e.path.endsWith(".rsc")) return false;
		return true;
	});
}
/**
* Walk the ranked traffic list, accumulating request counts until the
* coverage target is met or the hard cap is reached.
*/
function selectRoutes(traffic, coverageTarget, limit) {
	const totalRequests = traffic.reduce((sum, e) => sum + e.requests, 0);
	if (totalRequests === 0) return {
		routes: [],
		totalRequests: 0,
		coveredRequests: 0,
		coveragePercent: 0
	};
	const target = totalRequests * (coverageTarget / 100);
	const selected = [];
	let accumulated = 0;
	for (const entry of traffic) {
		if (accumulated >= target || selected.length >= limit) break;
		selected.push(entry);
		accumulated += entry.requests;
	}
	return {
		routes: selected,
		totalRequests,
		coveredRequests: accumulated,
		coveragePercent: accumulated / totalRequests * 100
	};
}
/** Pre-render port — high number to avoid collisions with dev servers. */
const PRERENDER_PORT = 19384;
/** Max time to wait for the local server to start (ms). */
const SERVER_STARTUP_TIMEOUT = 3e4;
/** Max concurrent fetch requests during pre-rendering. */
const FETCH_CONCURRENCY = 10;
/**
* Start a local production server, fetch each route to produce HTML,
* and return the results. Pages that fail to render are skipped.
*/
async function prerenderRoutes(routes, root, hostDomain) {
	const results = /* @__PURE__ */ new Map();
	let failedCount = 0;
	const port = PRERENDER_PORT;
	const distDir = path.join(root, "dist");
	if (!fs.existsSync(distDir)) {
		console.log("  TPR: Skipping pre-render — dist/ directory not found");
		return results;
	}
	const serverProcess = startLocalServer(root, port);
	try {
		await waitForServer(port, SERVER_STARTUP_TIMEOUT);
		for (let i = 0; i < routes.length; i += FETCH_CONCURRENCY) {
			const promises = routes.slice(i, i + FETCH_CONCURRENCY).map(async (routePath) => {
				try {
					const response = await fetch(`http://127.0.0.1:${port}${routePath}`, {
						headers: {
							"User-Agent": "vinext-tpr/1.0",
							...hostDomain ? { Host: hostDomain } : {}
						},
						redirect: "manual"
					});
					if (response.status < 400) {
						const html = await response.text();
						const headers = {};
						response.headers.forEach((value, key) => {
							if (key === "content-type" || key === "cache-control" || key === "x-vinext-revalidate" || key === "location") headers[key] = value;
						});
						results.set(routePath, {
							html,
							status: response.status,
							headers
						});
					}
				} catch {
					failedCount++;
				}
			});
			await Promise.all(promises);
		}
		if (failedCount > 0) console.log(`  TPR: ${failedCount} page(s) failed to pre-render (skipped)`);
	} finally {
		serverProcess.kill("SIGTERM");
		await new Promise((resolve) => {
			serverProcess.on("exit", resolve);
			setTimeout(resolve, 2e3);
		});
	}
	return results;
}
/**
* Spawn a subprocess running the vinext production server.
* Uses the same Node.js binary and resolves prod-server.js relative
* to the current module (works whether vinext is installed or linked).
*/
function startLocalServer(root, port) {
	const prodServerPath = path.resolve(import.meta.dirname, "..", "server", "prod-server.js");
	const outDir = path.join(root, "dist");
	const escapedProdServer = prodServerPath.replace(/\\/g, "\\\\");
	const escapedOutDir = outDir.replace(/\\/g, "\\\\");
	const script = [
		`import("file://${escapedProdServer}")`,
		`.then(m => m.startProdServer({ port: ${port}, host: "127.0.0.1", outDir: "${escapedOutDir}" }))`,
		`.catch(e => { console.error("[vinext-tpr] Server failed to start:", e); process.exit(1); });`
	].join("");
	const proc = spawn(process.execPath, [
		"--input-type=module",
		"-e",
		script
	], {
		cwd: root,
		stdio: "pipe",
		env: {
			...process.env,
			NODE_ENV: "production"
		}
	});
	proc.stderr?.on("data", (chunk) => {
		const msg = chunk.toString().trim();
		if (msg) console.error(`  [tpr-server] ${msg}`);
	});
	return proc;
}
/** Poll the local server until it responds or the timeout is reached. */
async function waitForServer(port, timeoutMs) {
	const start = Date.now();
	while (Date.now() - start < timeoutMs) try {
		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), 2e3);
		const response = await fetch(`http://127.0.0.1:${port}/`, {
			redirect: "manual",
			signal: controller.signal
		});
		clearTimeout(timer);
		await response.text();
		return;
	} catch {
		await new Promise((r) => setTimeout(r, 300));
	}
	throw new Error(`Local production server failed to start within ${timeoutMs / 1e3}s`);
}
/** KV bulk API accepts up to 10,000 pairs per request */
const KV_BATCH_SIZE = 1e4;
/** Maximum KV expiration TTL: 30 days */
const MAX_KV_TTL_SECONDS = 720 * 3600;
/**
* Build KV bulk API pairs from pre-rendered entries.
*
* Key format matches the runtime KVCacheHandler exactly:
*   ENTRY_PREFIX + isrCacheKey("app", pathname, buildId) + ":html"
*   → "cache:app:<buildId>:<pathname>:html"
*/
function buildTprKVPairs(entries, buildId, defaultRevalidateSeconds) {
	const now = Date.now();
	const pairs = [];
	for (const [routePath, result] of entries) {
		const revalidateHeader = result.headers[VINEXT_REVALIDATE_HEADER];
		const revalidateSeconds = revalidateHeader && !isNaN(Number(revalidateHeader)) ? Number(revalidateHeader) : defaultRevalidateSeconds;
		const revalidateAt = revalidateSeconds > 0 ? now + revalidateSeconds * 1e3 : null;
		const kvTtl = revalidateSeconds > 0 ? MAX_KV_TTL_SECONDS : 24 * 3600;
		const entry = {
			value: {
				kind: "APP_PAGE",
				html: result.html,
				headers: result.headers,
				status: result.status
			},
			tags: [],
			lastModified: now,
			revalidateAt
		};
		const cacheKey = ENTRY_PREFIX + isrCacheKey("app", routePath, buildId) + ":html";
		pairs.push({
			key: cacheKey,
			value: JSON.stringify(entry),
			expiration_ttl: kvTtl
		});
	}
	return pairs;
}
/**
* Upload pre-rendered pages to KV using the Cloudflare REST API.
* Writes in the same KVCacheEntry format that KVCacheHandler reads
* at runtime, so ISR serves these entries without any code changes.
*/
async function uploadToKV(entries, namespaceId, accountId, apiToken, defaultRevalidateSeconds, buildId) {
	const pairs = buildTprKVPairs(entries, buildId, defaultRevalidateSeconds);
	for (let i = 0; i < pairs.length; i += KV_BATCH_SIZE) {
		const batch = pairs.slice(i, i + KV_BATCH_SIZE);
		const response = await fetch(`https://api.cloudflare.com/client/v4/accounts/${accountId}/storage/kv/namespaces/${namespaceId}/bulk`, {
			method: "PUT",
			headers: {
				Authorization: `Bearer ${apiToken}`,
				"Content-Type": "application/json"
			},
			body: JSON.stringify(batch)
		});
		if (!response.ok) {
			const text = await response.text();
			throw new Error(`KV bulk upload failed (batch ${Math.floor(i / KV_BATCH_SIZE) + 1}): ${response.status} — ${text}`);
		}
	}
}
/** Default revalidation TTL for pre-rendered pages (1 hour). */
const DEFAULT_REVALIDATE_SECONDS = 3600;
/**
* Run the TPR pipeline: query traffic, select routes, pre-render, upload.
*
* Designed to be called between the build step and wrangler deploy in
* the `vinext deploy` pipeline. Gracefully skips (never errors) when
* the prerequisites aren't met.
*/
async function runTPR(options) {
	const startTime = Date.now();
	const { root, coverage, limit, window: windowHours } = options;
	const skip = (reason) => ({
		totalPaths: 0,
		prerenderedCount: 0,
		coverageAchieved: 0,
		durationMs: Date.now() - startTime,
		skipped: reason
	});
	const apiToken = process.env.CLOUDFLARE_API_TOKEN;
	if (!apiToken) return skip("no CLOUDFLARE_API_TOKEN set");
	const wranglerConfig = parseWranglerConfig(root);
	if (!wranglerConfig) return skip("could not parse wrangler config");
	if (!wranglerConfig.customDomain) return skip("no custom domain — zone analytics unavailable");
	if (!wranglerConfig.kvNamespaceId) return skip("no VINEXT_CACHE KV namespace configured");
	const accountId = wranglerConfig.accountId ?? await resolveAccountId(apiToken);
	if (!accountId) return skip("could not resolve Cloudflare account ID");
	console.log(`  TPR: Analyzing traffic for ${wranglerConfig.customDomain} (last ${windowHours}h)`);
	const zoneId = await resolveZoneId(wranglerConfig.customDomain, apiToken);
	if (!zoneId) return skip(`could not resolve zone for ${wranglerConfig.customDomain}`);
	let traffic;
	try {
		traffic = await queryTraffic(zoneId, apiToken, windowHours);
	} catch (err) {
		return skip(`analytics query failed: ${err instanceof Error ? err.message : String(err)}`);
	}
	if (traffic.length === 0) return skip("no traffic data available (first deploy?)");
	const selection = selectRoutes(traffic, coverage, limit);
	console.log(`  TPR: ${traffic.length.toLocaleString()} unique paths — ${selection.routes.length} pages cover ${Math.round(selection.coveragePercent)}% of traffic`);
	if (selection.routes.length === 0) return {
		totalPaths: traffic.length,
		prerenderedCount: 0,
		coverageAchieved: 0,
		durationMs: Date.now() - startTime,
		skipped: "no pre-renderable routes after filtering"
	};
	console.log(`  TPR: Pre-rendering ${selection.routes.length} pages...`);
	const routePaths = selection.routes.map((r) => r.path);
	let rendered;
	try {
		rendered = await prerenderRoutes(routePaths, root, wranglerConfig.customDomain);
	} catch (err) {
		return skip(`pre-rendering failed: ${err instanceof Error ? err.message : String(err)}`);
	}
	if (rendered.size === 0) return {
		totalPaths: traffic.length,
		prerenderedCount: 0,
		coverageAchieved: selection.coveragePercent,
		durationMs: Date.now() - startTime,
		skipped: "all pages failed to pre-render (request-dependent?)"
	};
	let buildId;
	try {
		buildId = fs.readFileSync(path.join(root, "dist", "server", "BUILD_ID"), "utf-8").trim();
	} catch {
		console.warn("  TPR: Could not read BUILD_ID from dist/server/ — KV keys will not match runtime. Skipping KV upload.");
		return skip("BUILD_ID not found in dist/server/ — build output may be incomplete");
	}
	try {
		await uploadToKV(rendered, wranglerConfig.kvNamespaceId, accountId, apiToken, DEFAULT_REVALIDATE_SECONDS, buildId);
	} catch (err) {
		return skip(`KV upload failed: ${err instanceof Error ? err.message : String(err)}`);
	}
	const durationMs = Date.now() - startTime;
	console.log(`  TPR: Pre-rendered ${rendered.size} pages in ${(durationMs / 1e3).toFixed(1)}s → KV cache`);
	return {
		totalPaths: traffic.length,
		prerenderedCount: rendered.size,
		coverageAchieved: selection.coveragePercent,
		durationMs
	};
}
//#endregion
export { buildTprKVPairs, domainCandidates, parseWranglerConfig, runTPR };

//# sourceMappingURL=tpr.js.map