import { pickRootParams, setRootParams } from "../shims/root-params.js";
//#region src/server/app-prerender-static-params.ts
async function callAppPrerenderStaticParams(options) {
	setRootParams(pickRootParams(options.params, options.rootParamNamesByPattern[options.pattern]));
	try {
		return await options.fn({ params: options.params });
	} finally {
		setRootParams(null);
	}
}
//#endregion
export { callAppPrerenderStaticParams };

//# sourceMappingURL=app-prerender-static-params.js.map