import { getOrCreateAls } from "./internal/als-registry.js";
import { getRequestContext, isInsideUnifiedScope, runWithUnifiedStateMutation } from "./unified-request-context.js";
import { _registerHeadStateAccessors } from "./head.js";
//#region src/shims/head-state.ts
const _FALLBACK_KEY = Symbol.for("vinext.head.fallback");
const _g = globalThis;
const _als = getOrCreateAls("vinext.head.als");
const _fallbackState = _g[_FALLBACK_KEY] ??= { ssrHeadChildren: [] };
function _getState() {
	if (isInsideUnifiedScope()) return getRequestContext();
	return _als.getStore() ?? _fallbackState;
}
function runWithHeadState(fn) {
	if (isInsideUnifiedScope()) return runWithUnifiedStateMutation((uCtx) => {
		uCtx.ssrHeadChildren = [];
	}, fn);
	return _als.run({ ssrHeadChildren: [] }, fn);
}
_registerHeadStateAccessors({
	getSSRHeadChildren() {
		return _getState().ssrHeadChildren;
	},
	resetSSRHead() {
		_getState().ssrHeadChildren = [];
	}
});
//#endregion
export { runWithHeadState };

//# sourceMappingURL=head-state.js.map