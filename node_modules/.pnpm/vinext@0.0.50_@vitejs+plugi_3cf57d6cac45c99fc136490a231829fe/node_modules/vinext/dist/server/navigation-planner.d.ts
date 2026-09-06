import { RouteManifest } from "../routing/app-route-graph.js";
import { NavigationTrace, NavigationTraceFields } from "./navigation-trace.js";

//#region src/server/navigation-planner.d.ts
type OperationLane = "hmr" | "navigation" | "prefetch" | "refresh" | "server-action" | "traverse";
type OperationToken = {
  operationId: number;
  lane: OperationLane;
  baseVisibleCommitVersion: number;
  graphVersion: string | null;
  deploymentVersion: string | null;
  targetSnapshotFingerprint: string;
  cacheVariantFingerprint?: string;
};
type RouteSnapshotV0 = {
  routeId: string;
  layoutIds: readonly string[];
  mountedParallelSlots: readonly MountedParallelSlotSnapshotV0[];
  rootBoundaryId: string | null;
  displayUrl: string;
  matchedUrl: string;
};
type MountedParallelSlotSnapshotV0 = {
  slotId: string;
  ownerLayoutId: string | null;
};
type NavigationPlannerStateV0 = {
  nextOperationToken: OperationToken;
  traceFields?: NavigationTraceFields;
  visibleCommitVersion: number;
  visibleSnapshot: RouteSnapshotV0;
};
type RefreshScope = "visible";
type NavigationEvent = {
  kind: "navigate";
  href: string;
  mode: "push" | "replace";
} | {
  kind: "refresh";
  scope: RefreshScope;
} | {
  kind: "traverse";
  direction: "back" | "forward";
  historyState: unknown;
} | {
  kind: "prefetch";
  href: string;
} | {
  kind: "flightResponseArrived";
  token: OperationToken;
  result: FlightResultV0;
};
type RequestedWork = {
  kind: "flight";
  href: string;
  mode: "push" | "replace" | "refresh";
} | {
  direction: "back" | "forward";
  historyState: unknown;
  kind: "traverseFlight";
} | {
  kind: "prefetch";
  href: string;
};
type CommitProposal = {
  preserveAbsentSlots: boolean;
  preserveElementIds: readonly string[];
  reason: "currentRootBoundary" | "rootBoundaryUnknownFallback";
  targetSnapshot: RouteSnapshotV0;
};
type NoCommitReason = "prefetchOnly";
type HardNavigationReason = "rootBoundaryChanged";
type RootBoundaryTransition = "currentRootBoundary" | "rootBoundaryChanged" | "rootBoundaryUnknownFallback";
type NavigationDecisionV0 = {
  kind: "requestWork";
  token: OperationToken;
  work: RequestedWork;
  trace: NavigationTrace;
} | {
  kind: "proposeCommit";
  token: OperationToken;
  proposal: CommitProposal;
  trace: NavigationTrace;
} | {
  kind: "noCommit";
  token: OperationToken;
  reason: NoCommitReason;
  trace: NavigationTrace;
} | {
  kind: "hardNavigate";
  token: OperationToken;
  url: string;
  reason: HardNavigationReason;
  trace: NavigationTrace;
};
type FlightResultV0 = {
  href: string;
  targetSnapshot: RouteSnapshotV0;
};
type NavigationPlannerInput = {
  routeManifest: RouteManifest | null;
  state: NavigationPlannerStateV0;
  event: NavigationEvent;
};
declare function classifyRootBoundaryTransition(currentRootBoundaryId: string | null, nextRootBoundaryId: string | null): RootBoundaryTransition;
declare function resolveSameLayoutAncestorPersistence(currentSnapshot: RouteSnapshotV0, targetSnapshot: RouteSnapshotV0): readonly string[];
declare function resolveMountedParallelSlotPersistence(currentSnapshot: RouteSnapshotV0, targetSnapshot: RouteSnapshotV0): readonly string[];
declare function resolveCurrentRootBoundaryElementPersistence(currentSnapshot: RouteSnapshotV0, targetSnapshot: RouteSnapshotV0): readonly string[];
declare function planNavigation(input: NavigationPlannerInput): NavigationDecisionV0;
declare const navigationPlanner: {
  classifyRootBoundaryTransition: typeof classifyRootBoundaryTransition;
  plan: typeof planNavigation;
  resolveCurrentRootBoundaryElementPersistence: typeof resolveCurrentRootBoundaryElementPersistence;
  resolveMountedParallelSlotPersistence: typeof resolveMountedParallelSlotPersistence;
  resolveSameLayoutAncestorPersistence: typeof resolveSameLayoutAncestorPersistence;
};
//#endregion
export { CommitProposal, FlightResultV0, HardNavigationReason, MountedParallelSlotSnapshotV0, NavigationDecisionV0, NavigationEvent, NavigationPlannerInput, NavigationPlannerStateV0, NoCommitReason, OperationLane, OperationToken, RefreshScope, RequestedWork, RootBoundaryTransition, RouteSnapshotV0, navigationPlanner };
//# sourceMappingURL=navigation-planner.d.ts.map