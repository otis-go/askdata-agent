import { setHeadersContext } from "../shims/headers.js";
import { setNavigationContext } from "../shims/navigation.js";
import { setRootParams } from "../shims/root-params.js";
//#region src/server/app-request-context.ts
/**
* Set navigation context in the ALS-backed store. "use client" components
* rendered during SSR need the pathname/searchParams/params but the SSR
* environment has a separate module instance of next/navigation.
*
* Clearing nav context (ctx === null) also clears root params.
*/
function setAppNavigationContext(ctx) {
	setNavigationContext(ctx);
	if (ctx === null) setRootParams(null);
}
/**
* Clear all per-request ALS state owned by the App Router handler.
* Must be called before returning a non-page response (redirect, public
* file proxy, etc.) to prevent state leaking between requests on Workers.
*
* Clears: headers, navigation context, root params.
*/
function clearAppRequestContext() {
	setHeadersContext(null);
	setAppNavigationContext(null);
}
//#endregion
export { clearAppRequestContext, setAppNavigationContext };

//# sourceMappingURL=app-request-context.js.map