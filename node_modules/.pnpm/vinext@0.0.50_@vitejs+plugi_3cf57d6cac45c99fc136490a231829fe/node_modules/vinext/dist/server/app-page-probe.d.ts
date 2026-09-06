import { LayoutFlags } from "./app-elements-wire.js";
import { AppPageSpecialError, LayoutClassificationOptions } from "./app-page-execution.js";

//#region src/server/app-page-probe.d.ts
type ProbeAppPageBeforeRenderResult = {
  response: Response | null;
  layoutFlags: LayoutFlags;
};
type ProbeAppPageBeforeRenderOptions = {
  hasLoadingBoundary: boolean;
  layoutCount: number;
  probeLayoutAt: (layoutIndex: number) => unknown;
  probePage: () => unknown;
  renderLayoutSpecialError: (specialError: AppPageSpecialError, layoutIndex: number) => Promise<Response>;
  renderPageSpecialError: (specialError: AppPageSpecialError) => Promise<Response>;
  resolveSpecialError: (error: unknown) => AppPageSpecialError | null;
  runWithSuppressedHookWarning<T>(probe: () => Promise<T>): Promise<T>; /** When provided, enables per-layout static/dynamic classification. */
  classification?: LayoutClassificationOptions | null;
};
declare function probeAppPageBeforeRender(options: ProbeAppPageBeforeRenderOptions): Promise<ProbeAppPageBeforeRenderResult>;
//#endregion
export { probeAppPageBeforeRender };
//# sourceMappingURL=app-page-probe.d.ts.map