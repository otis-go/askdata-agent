//#region src/server/dev-error-overlay-store.d.ts
type Source = "uncaught" | "caught" | "window-error" | "unhandledrejection";
type ReportedError = {
  source: Source;
  message: string;
  stack: string | undefined;
  componentStack: string | undefined;
};
type OverlayState = {
  errors: ReportedError[];
  index: number;
  minimized: boolean;
};
declare function subscribeOverlay(fn: () => void): () => void;
declare function getOverlaySnapshot(): OverlayState;
declare function reportToOverlay(error: ReportedError): void;
declare function dismissOverlay(): void;
declare function setOverlayIndex(index: number): void;
declare function minimizeOverlay(): void;
declare function expandOverlay(): void;
//#endregion
export { OverlayState, ReportedError, Source, dismissOverlay, expandOverlay, getOverlaySnapshot, minimizeOverlay, reportToOverlay, setOverlayIndex, subscribeOverlay };
//# sourceMappingURL=dev-error-overlay-store.d.ts.map