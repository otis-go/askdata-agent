import { getRequestContext, isInsideUnifiedScope } from "./unified-request-context.js";
//#region src/shims/root-params.ts
const _FALLBACK_KEY = Symbol.for("vinext.rootParams.fallback");
const _g = globalThis;
const _fallbackState = _g[_FALLBACK_KEY] ??= { rootParams: null };
function getState() {
	if (isInsideUnifiedScope()) return getRequestContext();
	return _fallbackState;
}
function pickRootParams(params, rootParamNames) {
	const picked = {};
	for (const name of rootParamNames ?? []) picked[name] = params[name];
	return picked;
}
function setRootParams(params) {
	getState().rootParams = params;
}
function getRootParam(name) {
	return Promise.resolve(getState().rootParams?.[name]);
}
//#endregion
export { getRootParam, pickRootParams, setRootParams };

//# sourceMappingURL=root-params.js.map