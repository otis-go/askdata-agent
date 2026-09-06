import { notFoundResponse } from "./http-error-responses.js";
import { isOpenRedirectShaped } from "./request-pipeline.js";
import { AppElementsWire } from "./app-elements-wire.js";
import "./app-elements.js";
import { ServerInsertedHTMLContext, clearServerInsertedHTML, renderServerInsertedHTML, setNavigationContext, useServerInsertedHTML } from "../shims/navigation.js";
import { runWithNavigationContext } from "../shims/navigation-state.js";
import { withScriptNonce } from "../shims/script-nonce-context.js";
import { createInlineScriptTag, createNonceAttribute, escapeHtmlAttr, safeJsonStringify } from "./html.js";
import { ElementsContext, Slot } from "../shims/slot.js";
import { RSC_FORM_STATE_GLOBAL } from "./app-browser-hydration.js";
import { createClientReferencePreloader } from "./app-client-reference-preloader.js";
import { deferUntilStreamConsumed } from "./app-page-stream.js";
import { createRscEmbedTransform, createTickBufferedTransform } from "./app-ssr-stream.js";
import { Fragment, createElement, use } from "react";
import { renderToReadableStream, renderToStaticMarkup } from "react-dom/server.edge";
import { createFromReadableStream } from "@vitejs/plugin-rsc/ssr";
import clientReferences from "virtual:vite-rsc/client-references";
//#region src/server/app-ssr-entry.ts
const clientReferencePreloader = createClientReferencePreloader({
	getReferences() {
		return clientReferences;
	},
	getClientRequire() {
		return globalThis.__vite_rsc_client_require__;
	},
	onPreloadError(id, error) {
		if (process.env.NODE_ENV !== "production") console.warn("[vinext] failed to preload client ref:", id, error);
	}
});
function ssrErrorDigest(input) {
	let hash = 5381;
	for (let i = input.length - 1; i >= 0; i--) hash = hash * 33 ^ input.charCodeAt(i);
	return (hash >>> 0).toString();
}
function getErrorMessage(error) {
	if (error instanceof Error) return error.message;
	if (typeof error === "string") return error;
	return Object.prototype.toString.call(error);
}
function renderInsertedHtml(insertedElements) {
	let insertedHTML = "";
	for (const element of insertedElements) try {
		insertedHTML += renderToStaticMarkup(createElement(Fragment, null, element));
	} catch {}
	return insertedHTML;
}
function renderFontHtml(fontData, nonce) {
	if (!fontData) return "";
	let fontHTML = "";
	const nonceAttr = createNonceAttribute(nonce);
	for (const url of fontData.links ?? []) fontHTML += `<link rel="stylesheet"${nonceAttr} href="${escapeHtmlAttr(url)}" />\n`;
	for (const preload of fontData.preloads ?? []) fontHTML += `<link rel="preload"${nonceAttr} href="${escapeHtmlAttr(preload.href)}" as="font" type="${escapeHtmlAttr(preload.type)}" crossorigin />\n`;
	if (fontData.styles && fontData.styles.length > 0) fontHTML += `<style data-vinext-fonts${nonceAttr}>${fontData.styles.join("\n")}</style>\n`;
	return fontHTML;
}
function extractModulePreloadHtml(bootstrapScriptContent, nonce) {
	if (!bootstrapScriptContent) return "";
	const match = bootstrapScriptContent.match(/import\("([^"]+)"\)/);
	if (!match?.[1]) return "";
	return `<link rel="modulepreload"${createNonceAttribute(nonce)} href="${escapeHtmlAttr(match[1])}" />\n`;
}
function buildHeadInjectionHtml(navContext, bootstrapScriptContent, formState, insertedHTML, fontHTML, scriptNonce) {
	const paramsScript = createInlineScriptTag("self.__VINEXT_RSC_PARAMS__=" + safeJsonStringify(navContext?.params ?? {}), scriptNonce);
	const navScript = createInlineScriptTag("self.__VINEXT_RSC_NAV__=" + safeJsonStringify({
		pathname: navContext?.pathname ?? "/",
		searchParams: navContext?.searchParams ? [...navContext.searchParams.entries()] : []
	}), scriptNonce);
	const formStateScript = formState === null ? "" : createInlineScriptTag("self[" + safeJsonStringify(RSC_FORM_STATE_GLOBAL) + "]=" + safeJsonStringify(formState), scriptNonce);
	return paramsScript + navScript + formStateScript + extractModulePreloadHtml(bootstrapScriptContent, scriptNonce) + insertedHTML + fontHTML;
}
async function handleSsr(rscStream, navContext, fontData, options) {
	return runWithNavigationContext(async () => {
		await clientReferencePreloader.preload();
		if (navContext) setNavigationContext(navContext);
		clearServerInsertedHTML();
		const cleanup = () => {
			setNavigationContext(null);
			clearServerInsertedHTML();
		};
		try {
			let ssrStream;
			let rscEmbed;
			if (options?.sideStream) {
				ssrStream = rscStream;
				rscEmbed = createRscEmbedTransform(options.sideStream, options?.scriptNonce);
				if (options.capturedRscDataRef) options.capturedRscDataRef.value = rscEmbed.getRawBuffer();
			} else {
				const [s1, s2] = rscStream.tee();
				ssrStream = s1;
				rscEmbed = createRscEmbedTransform(s2, options?.scriptNonce);
			}
			let flightRoot = null;
			function VinextFlightRoot() {
				if (!flightRoot) flightRoot = createFromReadableStream(ssrStream);
				const wireElements = use(flightRoot);
				const elements = AppElementsWire.decode(wireElements);
				const metadata = AppElementsWire.readMetadata(elements);
				return createElement(ElementsContext.Provider, { value: elements }, createElement(Slot, { id: metadata.routeId }));
			}
			const root = createElement(VinextFlightRoot);
			const ssrRoot = withScriptNonce(ServerInsertedHTMLContext ? createElement(ServerInsertedHTMLContext.Provider, { value: useServerInsertedHTML }, root) : root, options?.scriptNonce);
			const bootstrapScriptContent = await import.meta.viteRsc.loadBootstrapScriptContent("index");
			const htmlStream = await renderToReadableStream(ssrRoot, {
				bootstrapScriptContent,
				formState: options?.formState ?? null,
				nonce: options?.scriptNonce,
				onError(error) {
					if (error && typeof error === "object" && "digest" in error) return String(error.digest);
					if (process.env.NODE_ENV === "production" && error) return ssrErrorDigest(getErrorMessage(error) + (error instanceof Error ? error.stack ?? "" : ""));
				}
			});
			if (options?.waitForAllReady === true) await htmlStream.allReady;
			const fontHTML = renderFontHtml(fontData, options?.scriptNonce);
			let didInjectHeadHTML = false;
			const getInsertedHTML = () => {
				const insertedHTML = renderInsertedHtml(renderServerInsertedHTML());
				if (didInjectHeadHTML) return insertedHTML;
				didInjectHeadHTML = true;
				return buildHeadInjectionHtml(navContext, bootstrapScriptContent, options?.formState ?? null, insertedHTML, fontHTML, options?.scriptNonce);
			};
			return deferUntilStreamConsumed(htmlStream.pipeThrough(createTickBufferedTransform(rscEmbed, getInsertedHTML)), cleanup);
		} catch (error) {
			cleanup();
			throw error;
		}
	});
}
var app_ssr_entry_default = { async fetch(request) {
	if (isOpenRedirectShaped(new URL(request.url).pathname)) return notFoundResponse();
	const result = await (await import.meta.viteRsc.loadModule("rsc", "index")).default(request);
	if (result instanceof Response) return result;
	if (result == null) return notFoundResponse();
	return new Response(String(result), { status: 200 });
} };
//#endregion
export { app_ssr_entry_default as default, handleSsr };

//# sourceMappingURL=app-ssr-entry.js.map