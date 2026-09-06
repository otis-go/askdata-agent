//#region src/server/app-rsc-render-mode.ts
const APP_RSC_RENDER_MODE_NAVIGATION = "navigation";
const APP_RSC_RENDER_MODE_REFRESH_PRESERVE_UI = "refresh-preserve-ui";
const APP_RSC_RENDER_MODE_ACTION_RERENDER_PRESERVE_UI = "action-rerender-preserve-ui";
function shouldSuppressLoadingBoundaries(mode) {
	return mode === "refresh-preserve-ui" || mode === "action-rerender-preserve-ui";
}
function shouldUsePreserveUiCacheVariant(mode) {
	return shouldSuppressLoadingBoundaries(mode);
}
function parseAppRscRenderMode(value) {
	switch (value) {
		case APP_RSC_RENDER_MODE_REFRESH_PRESERVE_UI: return APP_RSC_RENDER_MODE_REFRESH_PRESERVE_UI;
		case APP_RSC_RENDER_MODE_ACTION_RERENDER_PRESERVE_UI: return APP_RSC_RENDER_MODE_ACTION_RERENDER_PRESERVE_UI;
		default: return APP_RSC_RENDER_MODE_NAVIGATION;
	}
}
//#endregion
export { APP_RSC_RENDER_MODE_ACTION_RERENDER_PRESERVE_UI, APP_RSC_RENDER_MODE_NAVIGATION, APP_RSC_RENDER_MODE_REFRESH_PRESERVE_UI, parseAppRscRenderMode, shouldSuppressLoadingBoundaries, shouldUsePreserveUiCacheVariant };

//# sourceMappingURL=app-rsc-render-mode.js.map