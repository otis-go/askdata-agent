import { ClientNavigationRenderSnapshot } from "../shims/navigation.js";
import { AppElements, LayoutFlags } from "./app-elements-wire.js";
import { NavigationTrace } from "./navigation-trace.js";
import { OperationLane } from "./navigation-planner.js";

//#region src/server/app-browser-state.d.ts
type HistoryStateRecord = {
  [key: string]: unknown;
};
type OperationRecordBase = {
  id: number;
  lane: OperationLane;
  startedVisibleCommitVersion: number;
};
type PendingOperationRecord = OperationRecordBase & {
  state: "pending";
};
type CommittedOperationRecord = OperationRecordBase & {
  state: "committed";
  visibleCommitVersion: number;
};
type OperationRecord = PendingOperationRecord | CommittedOperationRecord;
type AppRouterState = {
  activeOperation: OperationRecord | null;
  elements: AppElements;
  interceptionContext: string | null;
  layoutFlags: LayoutFlags;
  layoutIds: readonly string[];
  previousNextUrl: string | null;
  renderId: number;
  navigationSnapshot: ClientNavigationRenderSnapshot;
  rootLayoutTreePath: string | null;
  routeId: string;
  visibleCommitVersion: number;
};
type AppRouterAction = {
  elements: AppElements;
  interceptionContext: string | null;
  layoutFlags: LayoutFlags;
  layoutIds: readonly string[];
  navigationSnapshot: ClientNavigationRenderSnapshot;
  operation: PendingOperationRecord;
  previousNextUrl: string | null;
  renderId: number;
  rootLayoutTreePath: string | null;
  routeId: string;
  type: "navigate" | "replace" | "traverse";
};
type PendingNavigationCommit = {
  action: AppRouterAction;
  interceptionContext: string | null;
  previousNextUrl: string | null;
  rootLayoutTreePath: string | null;
  routeId: string;
};
type PendingNavigationCommitDisposition = "dispatch" | "hard-navigate" | "skip";
type DispatchPendingNavigationCommitDispositionDecision = {
  disposition: "dispatch";
  preserveAbsentSlots: boolean;
  preserveElementIds: readonly string[];
  trace: NavigationTrace;
};
type NonDispatchPendingNavigationCommitDispositionDecision = {
  disposition: Exclude<PendingNavigationCommitDisposition, "dispatch">;
  preserveElementIds: readonly [];
  trace: NavigationTrace;
};
type PendingNavigationCommitDispositionDecision = DispatchPendingNavigationCommitDispositionDecision | NonDispatchPendingNavigationCommitDispositionDecision;
declare function createHistoryStateWithPreviousNextUrl(state: unknown, previousNextUrl: string | null): HistoryStateRecord | null;
declare function readHistoryStatePreviousNextUrl(state: unknown): string | null;
declare function resolveInterceptionContextFromPreviousNextUrl(previousNextUrl: string | null, basePath?: string): string | null;
type ResolveServerActionRequestStateOptions = {
  actionId: string;
  basePath: string;
  elements: AppElements;
  previousNextUrl: string | null;
};
type ResolveServerActionRequestStateResult = {
  headers: Headers;
};
/**
 * Pure: builds the fetch Headers for a server-action POST. Carries the same
 * interception-context and mounted-slots headers the refresh path already
 * sends, so the server-action re-render can rebuild the intercepted tree
 * instead of replacing it with the direct route.
 *
 * Next.js sends `Next-URL: state.previousNextUrl || state.nextUrl` on action
 * POSTs when `hasInterceptionRouteInCurrentTree(state.tree)`. Vinext's
 * X-Vinext-Interception-Context is the equivalent signal for the server-side
 * `findIntercept` lookup.
 */
declare function resolveServerActionRequestState(options: ResolveServerActionRequestStateOptions): ResolveServerActionRequestStateResult;
declare function resolvePendingNavigationCommitDispositionDecision(options: {
  activeNavigationId: number;
  currentState: AppRouterState;
  pending: PendingNavigationCommit;
  startedNavigationId: number;
  targetHref?: string;
}): PendingNavigationCommitDispositionDecision;
declare function createPendingNavigationCommit(options: {
  currentState: AppRouterState;
  nextElements: Promise<AppElements>;
  navigationSnapshot: ClientNavigationRenderSnapshot;
  operationLane: OperationLane;
  previousNextUrl?: string | null;
  renderId: number;
  type: "navigate" | "replace" | "traverse";
}): Promise<PendingNavigationCommit>;
//#endregion
export { AppRouterAction, AppRouterState, CommittedOperationRecord, type OperationLane, OperationRecord, PendingNavigationCommit, PendingOperationRecord, createHistoryStateWithPreviousNextUrl, createPendingNavigationCommit, readHistoryStatePreviousNextUrl, resolveInterceptionContextFromPreviousNextUrl, resolvePendingNavigationCommitDispositionDecision, resolveServerActionRequestState };
//# sourceMappingURL=app-browser-state.d.ts.map