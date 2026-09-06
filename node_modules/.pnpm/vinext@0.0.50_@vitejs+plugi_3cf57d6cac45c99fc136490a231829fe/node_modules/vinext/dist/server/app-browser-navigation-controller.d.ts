import { ClientNavigationRenderSnapshot, commitClientNavigationState } from "../shims/navigation.js";
import { AppElements } from "./app-elements-wire.js";
import { OperationLane } from "./navigation-planner.js";
import { AppRouterState } from "./app-browser-state.js";
import { Dispatch, ReactNode } from "react";

//#region src/server/app-browser-navigation-controller.d.ts
type HistoryUpdateMode = "push" | "replace";
type PendingBrowserRouterState = {
  promise: Promise<AppRouterState>;
  resolve: (state: AppRouterState) => void;
  settled: boolean;
};
type NavigationPayloadOutcome = "committed" | "no-commit" | "hard-navigate";
type HardNavigationMode = "assign" | "replace";
type BrowserNavigationCommitEffectFactory = (options: {
  href: string;
  historyUpdateMode: HistoryUpdateMode | undefined;
  navId: number;
  params: Record<string, string | string[]>;
  previousNextUrl: string | null;
}) => () => void;
type BrowserRouterStateRef = {
  current: AppRouterState;
};
type BrowserNavigationControllerDeps = {
  commitClientNavigationState?: typeof commitClientNavigationState;
  performHardNavigation?: (href: string, mode?: HardNavigationMode) => boolean;
};
type BrowserNavigationController = {
  beginNavigation(): number;
  hasBrowserRouterState(): boolean;
  getBrowserRouterState(): AppRouterState;
  isCurrentNavigation(navId: number): boolean;
  waitForBrowserRouterStateReady(): Promise<void>;
  attachBrowserRouterState(setter: Dispatch<AppRouterState | Promise<AppRouterState>>, stateRef: BrowserRouterStateRef): () => void;
  beginPendingBrowserRouterState(): PendingBrowserRouterState;
  finalizeNavigation(navId: number, pending: PendingBrowserRouterState | null | undefined): void;
  renderNavigationPayload(options: {
    actionType: "navigate" | "replace" | "traverse";
    createNavigationCommitEffect: BrowserNavigationCommitEffectFactory;
    historyUpdateMode: HistoryUpdateMode | undefined;
    navigationSnapshot: ClientNavigationRenderSnapshot;
    nextElements: Promise<AppElements>;
    operationLane: OperationLane;
    params: Record<string, string | string[]>;
    pendingRouterState: PendingBrowserRouterState | null;
    previousNextUrl: string | null;
    targetHref: string;
    navId: number;
  }): Promise<NavigationPayloadOutcome>;
  commitSameUrlNavigatePayload(nextElements: Promise<AppElements>, navigationSnapshot: ClientNavigationRenderSnapshot, returnValue?: {
    ok: boolean;
    data: unknown;
  }, actionInitiationState?: AppRouterState): Promise<unknown>;
  hmrReplaceTree(nextElements: Promise<AppElements>, navigationSnapshot: ClientNavigationRenderSnapshot): Promise<void>;
  /**
   * Force-drain the queued pre-paint effect for the given renderId without
   * waiting for NavigationCommitSignal to commit. Used by the dev recovery
   * boundary in app-browser-entry.ts: when a render error replaces
   * NavigationCommitSignal with the boundary's null fallback, its
   * useLayoutEffect never fires, so the URL update for the in-flight
   * navigation would otherwise be lost.
   */
  drainPrePaintEffects(renderId: number): void;
  NavigationCommitSignal(this: void, {
    renderId,
    children
  }: {
    renderId: number;
    children?: ReactNode;
  }): ReactNode;
};
declare function clearHardNavigationLoopGuard(): void;
declare function createAppBrowserNavigationController(deps?: BrowserNavigationControllerDeps): BrowserNavigationController;
//#endregion
export { HistoryUpdateMode, NavigationPayloadOutcome, PendingBrowserRouterState, clearHardNavigationLoopGuard, createAppBrowserNavigationController };
//# sourceMappingURL=app-browser-navigation-controller.d.ts.map