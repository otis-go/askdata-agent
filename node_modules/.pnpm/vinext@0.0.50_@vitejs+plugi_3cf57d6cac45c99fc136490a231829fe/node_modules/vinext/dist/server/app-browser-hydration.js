//#region src/server/app-browser-hydration.ts
const RSC_FORM_STATE_GLOBAL = "__VINEXT_RSC_FORM_STATE__";
function consumeInitialFormState(global) {
	const formState = global["__VINEXT_RSC_FORM_STATE__"] ?? null;
	delete global[RSC_FORM_STATE_GLOBAL];
	return formState;
}
function createVinextHydrateRootOptions(options) {
	const hydrateOptions = {
		formState: options.formState,
		onUncaughtError: options.onUncaughtError
	};
	if (options.onCaughtError) return {
		...hydrateOptions,
		onCaughtError: options.onCaughtError
	};
	return hydrateOptions;
}
//#endregion
export { RSC_FORM_STATE_GLOBAL, consumeInitialFormState, createVinextHydrateRootOptions };

//# sourceMappingURL=app-browser-hydration.js.map