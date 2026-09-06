import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
//#region src/plugins/og-assets.ts
/**
* Create the `vinext:og-inline-fetch-assets` Vite plugin.
*
* Inlines binary assets that are runtime-fetched via
* `fetch(new URL("./asset", import.meta.url))` or read via
* `readFileSync(fileURLToPath(new URL("./asset", import.meta.url)))`.
* Both patterns are rewritten to inline base64 literals so the code works
* correctly inside Cloudflare Workers where `import.meta.url` is not a
* valid file URL.
*/
function createOgInlineFetchAssetsPlugin() {
	const cache = /* @__PURE__ */ new Map();
	let isBuild = false;
	return {
		name: "vinext:og-inline-fetch-assets",
		enforce: "pre",
		configResolved(config) {
			isBuild = config.command === "build";
		},
		buildStart() {
			if (isBuild) cache.clear();
		},
		async transform(code, id) {
			if (!code.includes("import.meta.url")) return null;
			const useCache = isBuild;
			const moduleDir = path.dirname(id);
			let newCode = code;
			let didReplace = false;
			const readAsBase64 = async (absPath) => {
				const cached = useCache ? cache.get(absPath) : void 0;
				if (cached !== void 0) return cached;
				try {
					const b64 = (await fs.promises.readFile(absPath)).toString("base64");
					if (useCache) cache.set(absPath, b64);
					return b64;
				} catch {
					return null;
				}
			};
			if (code.includes("fetch(")) for (const match of code.matchAll(/fetch\(\s*new URL\(\s*(["'])(\.\/[^"']+)\1\s*,\s*import\.meta\.url\s*\)\s*\)(?:\.then\(\s*(?:function\s*\([^)]*\)|\([^)]*\)\s*=>)\s*\{?\s*return\s+[^.]+\.arrayBuffer\(\)\s*\}?\s*\)|\.then\(\s*\([^)]*\)\s*=>\s*[^.]+\.arrayBuffer\(\)\s*\))/g)) {
				const fullMatch = match[0];
				const relPath = match[2];
				const fileBase64 = await readAsBase64(path.resolve(moduleDir, relPath));
				if (fileBase64 === null) continue;
				const inlined = [
					`(function(){`,
					`var b=${JSON.stringify(fileBase64)};`,
					`var r=atob(b);`,
					`var a=new Uint8Array(r.length);`,
					`for(var i=0;i<r.length;i++)a[i]=r.charCodeAt(i);`,
					`return Promise.resolve(a.buffer);`,
					`})()`
				].join("");
				newCode = newCode.replaceAll(fullMatch, inlined);
				didReplace = true;
			}
			if (code.includes("readFileSync(")) for (const match of newCode.matchAll(/[a-zA-Z_$][a-zA-Z0-9_$]*\.readFileSync\(\s*(?:[a-zA-Z_$][a-zA-Z0-9_$]*\.)?fileURLToPath\(\s*new URL\(\s*(["'])(\.\/[^"']+)\1\s*,\s*import\.meta\.url\s*\)\s*\)\s*\)/g)) {
				const fullMatch = match[0];
				const relPath = match[2];
				const fileBase64 = await readAsBase64(path.resolve(moduleDir, relPath));
				if (fileBase64 === null) continue;
				const inlined = `Buffer.from(${JSON.stringify(fileBase64)},"base64")`;
				newCode = newCode.replaceAll(fullMatch, inlined);
				didReplace = true;
			}
			if (!didReplace) return null;
			return {
				code: newCode,
				map: null
			};
		}
	};
}
/**
* The `vinext:og-assets` Vite plugin.
*
* Copies @vercel/og binary assets (e.g. resvg.wasm) to the RSC output
* directory for production builds. The edge build inlines fonts as base64 via
* `vinext:og-inline-fetch-assets`; this plugin is a safety net to ensure
* resvg.wasm exists in the output directory for the Node.js disk-read fallback.
*/
const ogAssetsPlugin = {
	name: "vinext:og-assets",
	apply: "build",
	enforce: "post",
	writeBundle: {
		sequential: true,
		order: "post",
		async handler(options) {
			if (this.environment?.name !== "rsc") return;
			const outDir = options.dir;
			if (!outDir) return;
			const indexPath = path.join(outDir, "index.js");
			if (!fs.existsSync(indexPath)) return;
			const content = fs.readFileSync(indexPath, "utf-8");
			const referencedAssets = ["resvg.wasm"].filter((asset) => content.includes(asset));
			if (referencedAssets.length === 0) return;
			try {
				const ogPkgPath = createRequire(import.meta.url).resolve("@vercel/og/package.json");
				const ogDistDir = path.join(path.dirname(ogPkgPath), "dist");
				for (const asset of referencedAssets) {
					const src = path.join(ogDistDir, asset);
					const dest = path.join(outDir, asset);
					if (fs.existsSync(src) && !fs.existsSync(dest)) fs.copyFileSync(src, dest);
				}
			} catch {}
		}
	}
};
//#endregion
export { createOgInlineFetchAssetsPlugin, ogAssetsPlugin };

//# sourceMappingURL=og-assets.js.map