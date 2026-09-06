//#region src/server/instrumentation-runtime.ts
let initialized = false;
let initPromise = null;
function isOnRequestErrorHandler(value) {
	return typeof value === "function";
}
/**
* Ensure the instrumentation module's `register()` and `onRequestError`
* hooks have been applied exactly once.
*
* @param instrumentationModule - The imported `instrumentation.ts` module.
*   Passed as an argument so the generated entry can import it normally
*   without this helper needing to know the module path.
*/
async function ensureInstrumentationRegistered(instrumentationModule) {
	if (process.env.VINEXT_PRERENDER === "1") return;
	if (initialized) return;
	if (initPromise) return initPromise;
	initPromise = (async () => {
		if (typeof instrumentationModule.register === "function") await instrumentationModule.register();
		if (isOnRequestErrorHandler(instrumentationModule.onRequestError)) globalThis.__VINEXT_onRequestErrorHandler__ = instrumentationModule.onRequestError;
		initialized = true;
	})();
	return initPromise;
}
//#endregion
export { ensureInstrumentationRegistered };

//# sourceMappingURL=instrumentation-runtime.js.map