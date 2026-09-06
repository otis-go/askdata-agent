//#region src/server/app-rsc-render-mode.d.ts
type AppRscRenderMode = "navigation" | "refresh-preserve-ui" | "action-rerender-preserve-ui";
declare const APP_RSC_RENDER_MODE_NAVIGATION = "navigation";
declare const APP_RSC_RENDER_MODE_REFRESH_PRESERVE_UI = "refresh-preserve-ui";
declare const APP_RSC_RENDER_MODE_ACTION_RERENDER_PRESERVE_UI = "action-rerender-preserve-ui";
declare function shouldSuppressLoadingBoundaries(mode: AppRscRenderMode): boolean;
declare function shouldUsePreserveUiCacheVariant(mode: AppRscRenderMode): boolean;
declare function parseAppRscRenderMode(value: string | null): AppRscRenderMode;
//#endregion
export { APP_RSC_RENDER_MODE_ACTION_RERENDER_PRESERVE_UI, APP_RSC_RENDER_MODE_NAVIGATION, APP_RSC_RENDER_MODE_REFRESH_PRESERVE_UI, AppRscRenderMode, parseAppRscRenderMode, shouldSuppressLoadingBoundaries, shouldUsePreserveUiCacheVariant };
//# sourceMappingURL=app-rsc-render-mode.d.ts.map