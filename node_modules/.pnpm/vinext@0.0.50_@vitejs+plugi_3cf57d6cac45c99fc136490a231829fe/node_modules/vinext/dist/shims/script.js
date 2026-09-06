"use client";
import { escapeInlineContent } from "./head.js";
import { useScriptNonce } from "./script-nonce-context.js";
import React, { useEffect, useRef } from "react";
//#region src/shims/script.tsx
/**
* next/script shim
*
* Provides the <Script> component for loading third-party scripts with
* configurable loading strategies.
*
* Strategies:
*   - "beforeInteractive": rendered as a <script> tag in SSR output
*   - "afterInteractive" (default): loaded client-side after hydration
*   - "lazyOnload": deferred until window.load + requestIdleCallback
*   - "worker": sets type="text/partytown" (requires Partytown setup)
*/
const loadedScripts = /* @__PURE__ */ new Set();
function getClientAutoNonce() {
	if (typeof document === "undefined") return void 0;
	const existingNonceElement = document.querySelector("[nonce]");
	if (!(existingNonceElement instanceof HTMLElement)) return;
	return existingNonceElement.nonce || existingNonceElement.getAttribute("nonce") || void 0;
}
function resolveScriptNonce(explicitNonce, contextualNonce) {
	if (typeof explicitNonce === "string" && explicitNonce.length > 0) return explicitNonce;
	if (typeof window === "undefined") return contextualNonce;
	return getClientAutoNonce();
}
function buildBeforeInteractiveScriptProps(options) {
	const scriptProps = { ...options.rest };
	if (options.src) scriptProps.src = options.src;
	if (options.id) scriptProps.id = options.id;
	if (options.resolvedNonce) scriptProps.nonce = options.resolvedNonce;
	if (options.dangerouslySetInnerHTML) scriptProps.dangerouslySetInnerHTML = { __html: escapeInlineContent(options.dangerouslySetInnerHTML.__html, "script") };
	return scriptProps;
}
/**
* Load a script imperatively (outside of React).
*/
function handleClientScriptLoad(props) {
	const { src, id, onLoad, onError, strategy: _strategy, onReady: _onReady, children, ...rest } = props;
	if (typeof window === "undefined") return;
	const key = id ?? src ?? "";
	if (key && loadedScripts.has(key)) return;
	const el = document.createElement("script");
	if (src) el.src = src;
	if (id) el.id = id;
	const resolvedNonce = resolveScriptNonce(rest.nonce);
	for (const [attr, value] of Object.entries(rest)) {
		if (attr === "dangerouslySetInnerHTML" || attr === "className") continue;
		if (typeof value === "string") el.setAttribute(attr, value);
		else if (typeof value === "boolean" && value) el.setAttribute(attr, "");
	}
	if (resolvedNonce && !el.getAttribute("nonce")) el.setAttribute("nonce", resolvedNonce);
	if (children && typeof children === "string") el.textContent = children;
	if (onLoad) el.addEventListener("load", onLoad);
	if (onError) el.addEventListener("error", onError);
	document.body.appendChild(el);
	if (key) loadedScripts.add(key);
}
/**
* Initialize multiple scripts at once (called during app bootstrap).
*/
function initScriptLoader(scripts) {
	for (const script of scripts) handleClientScriptLoad(script);
}
function Script(props) {
	const { src, id, strategy = "afterInteractive", onLoad, onReady, onError, children, dangerouslySetInnerHTML, ...rest } = props;
	const hasMounted = useRef(false);
	const key = id ?? src ?? "";
	const contextualNonce = useScriptNonce();
	const resolvedNonce = resolveScriptNonce(rest.nonce, contextualNonce);
	useEffect(() => {
		if (hasMounted.current) return;
		hasMounted.current = true;
		if (strategy === "beforeInteractive") return;
		if (key && loadedScripts.has(key)) {
			onReady?.();
			return;
		}
		const load = () => {
			if (key && loadedScripts.has(key)) {
				onReady?.();
				return;
			}
			const el = document.createElement("script");
			if (src) el.src = src;
			if (id) el.id = id;
			for (const [attr, value] of Object.entries(rest)) if (attr === "className") el.setAttribute("class", String(value));
			else if (typeof value === "string") el.setAttribute(attr, value);
			else if (typeof value === "boolean" && value) el.setAttribute(attr, "");
			if (resolvedNonce && !el.getAttribute("nonce")) el.setAttribute("nonce", resolvedNonce);
			if (strategy === "worker") el.setAttribute("type", "text/partytown");
			if (dangerouslySetInnerHTML?.__html) el.innerHTML = dangerouslySetInnerHTML.__html;
			else if (children && typeof children === "string") el.textContent = children;
			el.addEventListener("load", (e) => {
				if (key) loadedScripts.add(key);
				onLoad?.(e);
				onReady?.();
			});
			if (onError) el.addEventListener("error", onError);
			document.body.appendChild(el);
		};
		if (strategy === "lazyOnload") if (document.readyState === "complete") if (typeof requestIdleCallback === "function") requestIdleCallback(load);
		else setTimeout(load, 1);
		else window.addEventListener("load", () => {
			if (typeof requestIdleCallback === "function") requestIdleCallback(load);
			else setTimeout(load, 1);
		});
		else load();
	}, [
		src,
		id,
		strategy,
		onLoad,
		onReady,
		onError,
		children,
		dangerouslySetInnerHTML,
		key,
		resolvedNonce,
		rest
	]);
	if (typeof window === "undefined") {
		if (strategy === "beforeInteractive") return React.createElement("script", buildBeforeInteractiveScriptProps({
			src,
			id,
			rest,
			resolvedNonce,
			dangerouslySetInnerHTML
		}), children);
		return null;
	}
	if (strategy === "beforeInteractive") return React.createElement("script", buildBeforeInteractiveScriptProps({
		src,
		id,
		rest,
		resolvedNonce,
		dangerouslySetInnerHTML
	}), children);
	return null;
}
//#endregion
export { Script as default, handleClientScriptLoad, initScriptLoader };

//# sourceMappingURL=script.js.map