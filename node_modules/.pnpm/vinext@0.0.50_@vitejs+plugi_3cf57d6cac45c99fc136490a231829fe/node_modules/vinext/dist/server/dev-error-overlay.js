import { isNavigationSignalError } from "../utils/navigation-signal.js";
import { dismissOverlay, expandOverlay, getOverlaySnapshot, minimizeOverlay, reportToOverlay, setOverlayIndex, subscribeOverlay } from "./dev-error-overlay-store.js";
import { useEffect, useSyncExternalStore } from "react";
import { Fragment as Fragment$1, jsx, jsxs } from "react/jsx-runtime";
import { createRoot } from "react-dom/client";
//#region src/server/dev-error-overlay.tsx
const MOUNT_NODE_ID = "__vinext_dev_error_overlay_root";
let reactRoot = null;
let installed = false;
const reportedErrors = /* @__PURE__ */ new WeakSet();
function rememberReported(error) {
	if (error && typeof error === "object") reportedErrors.add(error);
}
function alreadyReported(error) {
	return !!error && typeof error === "object" && reportedErrors.has(error);
}
function installDevErrorOverlay() {
	if (installed || typeof window === "undefined") return;
	installed = true;
	window.addEventListener("error", (event) => {
		const err = event.error;
		if (isNavigationSignalError(err)) return;
		if (err instanceof Error) {
			if (alreadyReported(err)) return;
			reportDevError(err, { source: "window-error" });
		} else if (event.message) reportDevError(new Error(event.message), { source: "window-error" });
	});
	window.addEventListener("unhandledrejection", (event) => {
		const reason = event.reason;
		if (isNavigationSignalError(reason)) return;
		if (reason instanceof Error) {
			if (alreadyReported(reason)) return;
			reportDevError(reason, { source: "unhandledrejection" });
		} else reportDevError(new Error(String(reason)), { source: "unhandledrejection" });
	});
}
function reportDevError(error, options) {
	if (typeof window === "undefined") return;
	rememberReported(error);
	const message = error instanceof Error ? error.message : typeof error === "string" ? error : safeStringify(error);
	const stack = error instanceof Error ? error.stack : void 0;
	ensureMounted();
	reportToOverlay({
		source: options.source,
		message,
		stack,
		componentStack: options.componentStack
	});
}
function devOnCaughtError(error, errorInfo) {
	if (isNavigationSignalError(error)) return;
	console.error(error);
	if (errorInfo?.componentStack) console.error("The above error occurred in a React component:\n" + errorInfo.componentStack);
	reportDevError(error, {
		source: "caught",
		componentStack: errorInfo?.componentStack
	});
}
function devOnUncaughtError(error, errorInfo) {
	if (isNavigationSignalError(error)) return;
	console.error(error);
	if (errorInfo?.componentStack) console.error("The above error occurred in a React component:\n" + errorInfo.componentStack);
	reportDevError(error, {
		source: "uncaught",
		componentStack: errorInfo?.componentStack
	});
}
function safeStringify(value) {
	try {
		return JSON.stringify(value);
	} catch {
		return Object.prototype.toString.call(value);
	}
}
function ensureMounted() {
	if (reactRoot) return;
	const node = document.createElement("div");
	node.id = MOUNT_NODE_ID;
	(document.body ?? document.documentElement).appendChild(node);
	reactRoot = createRoot(node);
	reactRoot.render(/* @__PURE__ */ jsx(DevErrorOverlayApp, {}));
}
const SOURCE_LABEL = {
	uncaught: "Unhandled Runtime Error",
	caught: "Runtime Error",
	"window-error": "Unhandled Script Error",
	unhandledrejection: "Unhandled Promise Rejection"
};
function DevErrorOverlayApp() {
	const state = useSyncExternalStore(subscribeOverlay, getOverlaySnapshot, getOverlaySnapshot);
	if (state.errors.length === 0) return null;
	const current = state.errors[state.index] ?? state.errors[0];
	return /* @__PURE__ */ jsxs(Fragment$1, { children: [/* @__PURE__ */ jsx("style", { children: overlayStylesheet }), state.minimized ? /* @__PURE__ */ jsx(DevErrorIndicator, {
		count: state.errors.length,
		source: current.source,
		onExpand: expandOverlay
	}) : /* @__PURE__ */ jsx(DevErrorOverlay, {
		error: current,
		index: state.index,
		total: state.errors.length,
		onPrev: () => setOverlayIndex(state.index - 1),
		onNext: () => setOverlayIndex(state.index + 1),
		onMinimize: minimizeOverlay,
		onDismiss: dismissOverlay
	})] });
}
function DevErrorIndicator({ count, source, onExpand }) {
	return /* @__PURE__ */ jsx("div", {
		style: indicatorContainerStyle,
		children: /* @__PURE__ */ jsxs("button", {
			type: "button",
			"data-testid": "vinext-dev-error-indicator",
			"aria-label": `${count} runtime error${count === 1 ? "" : "s"} — click to expand`,
			title: SOURCE_LABEL[source],
			onClick: onExpand,
			className: "vinext-overlay-indicator",
			children: [/* @__PURE__ */ jsx("span", {
				"aria-hidden": "true",
				style: indicatorIconStyle,
				children: "⚠"
			}), /* @__PURE__ */ jsx("span", {
				"data-testid": "vinext-dev-error-indicator-count",
				style: indicatorCountStyle,
				children: count
			})]
		})
	});
}
function DevErrorOverlay({ error, index, total, onPrev, onNext, onMinimize, onDismiss }) {
	const frames = error.stack ? parseStack(error.stack) : [];
	useEffect(() => {
		const onKey = (e) => {
			if (e.key === "Escape") onMinimize();
			else if (e.key === "ArrowLeft" && total > 1) onPrev();
			else if (e.key === "ArrowRight" && total > 1) onNext();
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [
		onMinimize,
		onPrev,
		onNext,
		total
	]);
	return /* @__PURE__ */ jsx("div", {
		style: backdropStyle,
		"data-testid": "vinext-dev-error-backdrop",
		onClick: onMinimize,
		children: /* @__PURE__ */ jsxs("div", {
			role: "dialog",
			"aria-modal": "true",
			"aria-label": SOURCE_LABEL[error.source],
			"data-testid": "vinext-dev-error-overlay",
			style: dialogStyle,
			onClick: (e) => e.stopPropagation(),
			children: [
				/* @__PURE__ */ jsx("div", { style: accentBarStyle }),
				/* @__PURE__ */ jsxs("header", {
					style: headerStyle,
					children: [
						/* @__PURE__ */ jsxs("div", {
							style: headerLeftStyle,
							children: [/* @__PURE__ */ jsx("span", {
								"data-testid": "vinext-dev-error-title",
								style: badgeStyle,
								children: SOURCE_LABEL[error.source]
							}), total > 1 ? /* @__PURE__ */ jsxs("div", {
								"data-testid": "vinext-dev-error-pagination",
								style: paginationStyle,
								children: [
									/* @__PURE__ */ jsx("button", {
										type: "button",
										"data-testid": "vinext-dev-error-prev",
										onClick: onPrev,
										disabled: index === 0,
										className: "vinext-overlay-nav",
										"aria-label": "Previous error",
										children: "‹"
									}),
									/* @__PURE__ */ jsxs("span", {
										"data-testid": "vinext-dev-error-counter",
										style: counterStyle,
										children: [
											index + 1,
											" of ",
											total
										]
									}),
									/* @__PURE__ */ jsx("button", {
										type: "button",
										"data-testid": "vinext-dev-error-next",
										onClick: onNext,
										disabled: index === total - 1,
										className: "vinext-overlay-nav",
										"aria-label": "Next error",
										children: "›"
									})
								]
							}) : null]
						}),
						/* @__PURE__ */ jsx("button", {
							type: "button",
							"data-testid": "vinext-dev-error-minimize",
							onClick: onMinimize,
							className: "vinext-overlay-minimize",
							"aria-label": "Minimize",
							title: "Minimize (Esc)",
							children: "–"
						}),
						/* @__PURE__ */ jsx("button", {
							type: "button",
							"data-testid": "vinext-dev-error-close",
							onClick: onDismiss,
							className: "vinext-overlay-close",
							"aria-label": "Dismiss",
							title: "Dismiss all errors",
							children: "×"
						})
					]
				}),
				/* @__PURE__ */ jsxs("div", {
					style: bodyStyle,
					children: [
						/* @__PURE__ */ jsx("h2", {
							"data-testid": "vinext-dev-error-message",
							style: messageStyle,
							children: error.message
						}),
						frames.length > 0 ? /* @__PURE__ */ jsx("ol", {
							"data-testid": "vinext-dev-error-stack",
							style: stackListStyle,
							children: frames.map((frame) => /* @__PURE__ */ jsxs("li", {
								className: "vinext-overlay-frame",
								style: stackItemStyle,
								children: [/* @__PURE__ */ jsx("span", {
									style: frameFnStyle,
									children: frame.fn
								}), frame.file ? /* @__PURE__ */ jsxs("span", {
									style: frameLocStyle,
									children: [
										frame.file,
										frame.line ? `:${frame.line}` : "",
										frame.col ? `:${frame.col}` : ""
									]
								}) : null]
							}, frame.key))
						}) : null,
						error.componentStack ? /* @__PURE__ */ jsxs("details", {
							style: detailsStyle,
							children: [/* @__PURE__ */ jsx("summary", {
								style: summaryStyle,
								children: "Component stack"
							}), /* @__PURE__ */ jsx("pre", {
								"data-testid": "vinext-dev-error-component-stack",
								style: componentStackStyle,
								children: error.componentStack
							})]
						}) : null
					]
				})
			]
		})
	});
}
const V8_PAREN_FRAME = /^(.*?)\s*\((.+):(\d+):(\d+)\)$/;
const V8_BARE_FRAME = /^(.+):(\d+):(\d+)$/;
const MOZ_FRAME = /^(.*?)@(.+):(\d+):(\d+)$/;
function parseStack(stack) {
	const frames = [];
	const seen = /* @__PURE__ */ new Map();
	const pushFrame = (fn, file, line, col) => {
		const base = `${fn}@${file ?? ""}:${line ?? ""}:${col ?? ""}`;
		const count = (seen.get(base) ?? 0) + 1;
		seen.set(base, count);
		const key = count === 1 ? base : `${base}#${count}`;
		frames.push({
			key,
			fn,
			file,
			line,
			col
		});
	};
	for (const raw of stack.split("\n")) {
		const line = raw.trim();
		if (!line) continue;
		if (line.startsWith("at ")) {
			const body = line.slice(3);
			const parenMatch = body.match(V8_PAREN_FRAME);
			if (parenMatch) {
				pushFrame(parenMatch[1] || "<anonymous>", parenMatch[2], parenMatch[3], parenMatch[4]);
				continue;
			}
			const bareMatch = body.match(V8_BARE_FRAME);
			if (bareMatch) {
				pushFrame("<anonymous>", bareMatch[1], bareMatch[2], bareMatch[3]);
				continue;
			}
			pushFrame(body);
			continue;
		}
		const mozMatch = line.match(MOZ_FRAME);
		if (mozMatch) {
			pushFrame(mozMatch[1] || "<anonymous>", mozMatch[2], mozMatch[3], mozMatch[4]);
			continue;
		}
		pushFrame(line);
	}
	return frames;
}
const FONT_STACK = "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
const MONO_STACK = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
const overlayStylesheet = `
@keyframes vinextOverlayBackdropIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes vinextOverlayDialogIn {
  from { opacity: 0; transform: translateY(8px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
@keyframes vinextOverlayIndicatorIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
.vinext-overlay-nav {
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
  padding: 2px 8px;
  font-size: 14px;
  line-height: 1;
  border-radius: 6px;
  transition: background 0.12s ease;
}
.vinext-overlay-nav:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.08);
}
.vinext-overlay-nav:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.vinext-overlay-minimize,
.vinext-overlay-close {
  background: transparent;
  border: none;
  color: #a1a1aa;
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
  padding: 4px 8px;
  border-radius: 6px;
  transition: background 0.12s ease, color 0.12s ease;
}
.vinext-overlay-minimize:hover,
.vinext-overlay-close:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fafafa;
}
.vinext-overlay-close { font-size: 20px; }
.vinext-overlay-frame {
  padding: 8px 12px;
  border-radius: 6px;
  transition: background 0.12s ease;
}
.vinext-overlay-frame:hover {
  background: rgba(255, 255, 255, 0.04);
}
.vinext-overlay-indicator {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: 999px;
  background: #18181b;
  color: #fafafa;
  border: 1px solid rgba(239, 68, 68, 0.45);
  font: 600 13px ${FONT_STACK};
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease, transform 0.12s ease;
  animation: vinextOverlayIndicatorIn 0.18s ease-out;
}
.vinext-overlay-indicator:hover {
  background: #1f1f23;
  border-color: rgba(239, 68, 68, 0.7);
  transform: translateY(-1px);
}
`;
const backdropStyle = {
	position: "fixed",
	inset: 0,
	background: "rgba(10, 10, 12, 0.55)",
	backdropFilter: "blur(3px)",
	WebkitBackdropFilter: "blur(3px)",
	display: "flex",
	alignItems: "center",
	justifyContent: "center",
	padding: 24,
	zIndex: 2147483646,
	animation: "vinextOverlayBackdropIn 0.15s ease-out"
};
const dialogStyle = {
	position: "relative",
	pointerEvents: "auto",
	width: "min(640px, 100%)",
	maxHeight: "min(80vh, 720px)",
	display: "flex",
	flexDirection: "column",
	background: "#0a0a0a",
	color: "#fafafa",
	border: "1px solid rgba(255, 255, 255, 0.08)",
	borderRadius: 12,
	fontFamily: FONT_STACK,
	fontSize: 14,
	lineHeight: 1.5,
	overflow: "hidden",
	animation: "vinextOverlayDialogIn 0.18s ease-out"
};
const indicatorContainerStyle = {
	position: "fixed",
	bottom: 16,
	left: 16,
	zIndex: 2147483646
};
const indicatorIconStyle = {
	display: "inline-flex",
	alignItems: "center",
	justifyContent: "center",
	color: "#ef4444",
	fontSize: 14
};
const indicatorCountStyle = {
	display: "inline-flex",
	alignItems: "center",
	justifyContent: "center",
	minWidth: 18,
	padding: "0 6px",
	height: 18,
	borderRadius: 999,
	background: "rgba(239, 68, 68, 0.18)",
	color: "#fca5a5",
	fontSize: 11,
	fontWeight: 600,
	fontVariantNumeric: "tabular-nums"
};
const accentBarStyle = {
	height: 3,
	background: "linear-gradient(90deg, #ef4444 0%, #f97316 100%)"
};
const headerStyle = {
	display: "flex",
	alignItems: "center",
	justifyContent: "space-between",
	gap: 12,
	padding: "14px 16px",
	borderBottom: "1px solid rgba(255, 255, 255, 0.06)"
};
const headerLeftStyle = {
	display: "flex",
	alignItems: "center",
	gap: 10,
	minWidth: 0
};
const badgeStyle = {
	display: "inline-flex",
	alignItems: "center",
	background: "rgba(239, 68, 68, 0.12)",
	color: "#fca5a5",
	border: "1px solid rgba(239, 68, 68, 0.25)",
	padding: "3px 10px",
	borderRadius: 999,
	fontSize: 11,
	fontWeight: 600,
	letterSpacing: .2,
	textTransform: "uppercase",
	whiteSpace: "nowrap"
};
const paginationStyle = {
	display: "flex",
	alignItems: "center",
	gap: 2,
	color: "#a1a1aa",
	fontSize: 12
};
const counterStyle = {
	padding: "0 4px",
	fontVariantNumeric: "tabular-nums"
};
const bodyStyle = {
	padding: "16px 20px 20px",
	overflow: "auto",
	flex: 1
};
const messageStyle = {
	margin: "0 0 16px 0",
	fontFamily: MONO_STACK,
	fontSize: 16,
	fontWeight: 500,
	lineHeight: 1.45,
	color: "#fafafa",
	whiteSpace: "pre-wrap",
	wordBreak: "break-word"
};
const stackListStyle = {
	listStyle: "none",
	margin: 0,
	padding: 0,
	display: "flex",
	flexDirection: "column",
	gap: 2,
	fontFamily: MONO_STACK,
	fontSize: 12
};
const stackItemStyle = {
	display: "flex",
	flexDirection: "column",
	gap: 2,
	cursor: "default"
};
const frameFnStyle = {
	color: "#fafafa",
	fontWeight: 500
};
const frameLocStyle = {
	color: "#71717a",
	fontSize: 11
};
const detailsStyle = {
	marginTop: 16,
	paddingTop: 12,
	borderTop: "1px solid rgba(255, 255, 255, 0.06)",
	color: "#a1a1aa",
	fontSize: 12
};
const summaryStyle = {
	cursor: "pointer",
	userSelect: "none",
	padding: "4px 0",
	color: "#a1a1aa",
	fontWeight: 500
};
const componentStackStyle = {
	margin: "8px 0 0 0",
	fontFamily: MONO_STACK,
	whiteSpace: "pre-wrap",
	wordBreak: "break-word",
	color: "#a1a1aa"
};
//#endregion
export { devOnCaughtError, devOnUncaughtError, dismissOverlay, installDevErrorOverlay };

//# sourceMappingURL=dev-error-overlay.js.map