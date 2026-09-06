import { ClientNavigationRenderSnapshot } from "../shims/navigation.js";
import { AppElements } from "./app-elements-wire.js";
import { NavigationTrace } from "./navigation-trace.js";
import { OperationLane } from "./navigation-planner.js";
import { AppRouterAction, AppRouterState, PendingNavigationCommit } from "./app-browser-state.js";

//#region src/server/app-browser-visible-commit.d.ts
type VisibleCommitDecision = {
  disposition: "commit";
  preserveAbsentSlots: boolean;
  preserveElementIds: readonly string[];
  trace: NavigationTrace;
};
type HardNavigateCommitDecision = {
  disposition: "hard-navigate";
  trace: NavigationTrace;
};
type NoCommitDecision = {
  disposition: "no-commit";
  trace: NavigationTrace;
};
type CommitDecision = VisibleCommitDecision | HardNavigateCommitDecision | NoCommitDecision;
declare const approvedVisibleCommitBrand: unique symbol;
type ApprovedVisibleCommit = {
  readonly [approvedVisibleCommitBrand]: true;
  readonly action: AppRouterAction;
  readonly decision: VisibleCommitDecision;
  readonly interceptionContext: string | null;
  readonly previousNextUrl: string | null;
  readonly rootLayoutTreePath: string | null;
  readonly routeId: string;
};
type VisibleCommitApproval = {
  approvedCommit: ApprovedVisibleCommit;
  decision: VisibleCommitDecision;
};
type NonVisibleCommitApproval = {
  approvedCommit: null;
  decision: HardNavigateCommitDecision | NoCommitDecision;
};
type CommitApproval = VisibleCommitApproval | NonVisibleCommitApproval;
type ClassifiedPendingNavigationCommit = {
  approvedCommit: ApprovedVisibleCommit | null;
  decision: CommitDecision;
  pending: PendingNavigationCommit;
  trace: NavigationTrace;
};
declare function applyApprovedVisibleCommit(state: AppRouterState, commit: ApprovedVisibleCommit): AppRouterState;
declare function approveHmrVisibleCommit(pending: PendingNavigationCommit): ApprovedVisibleCommit;
declare function approvePendingNavigationCommit(options: {
  activeNavigationId: number;
  currentState: AppRouterState;
  pending: PendingNavigationCommit;
  startedNavigationId: number;
  targetHref: string;
}): CommitApproval;
declare function resolveAndClassifyNavigationCommit(options: {
  activeNavigationId: number;
  currentState: AppRouterState;
  getActiveNavigationId?: () => number;
  getCurrentStateForApproval?: () => AppRouterState;
  navigationSnapshot: ClientNavigationRenderSnapshot;
  nextElements: Promise<AppElements>;
  operationLane: OperationLane;
  previousNextUrl?: string | null;
  renderId: number;
  startedNavigationId: number;
  targetHref: string;
  type: "navigate" | "replace" | "traverse";
}): Promise<ClassifiedPendingNavigationCommit>;
//#endregion
export { ApprovedVisibleCommit, applyApprovedVisibleCommit, approveHmrVisibleCommit, approvePendingNavigationCommit, resolveAndClassifyNavigationCommit };
//# sourceMappingURL=app-browser-visible-commit.d.ts.map