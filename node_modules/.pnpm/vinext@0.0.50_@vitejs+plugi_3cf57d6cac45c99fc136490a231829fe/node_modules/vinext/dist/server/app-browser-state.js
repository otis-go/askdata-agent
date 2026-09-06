import { stripBasePath } from "../utils/base-path.js";
import { RSC_ACTION_HEADER, VINEXT_INTERCEPTION_CONTEXT_HEADER, VINEXT_MOUNTED_SLOTS_HEADER } from "./headers.js";
import { AppElementsWire } from "./app-elements-wire.js";
import { getMountedSlotIds, getMountedSlotIdsHeader } from "./app-elements.js";
import { createRscRequestHeaders } from "./app-rsc-cache-busting.js";
import { NavigationTraceReasonCodes, createNavigationLifecycleTraceFields, createNavigationTrace } from "./navigation-trace.js";
import { navigationPlanner } from "./navigation-planner.js";
//#region src/server/app-browser-state.ts
const VINEXT_PREVIOUS_NEXT_URL_HISTORY_STATE_KEY = "__vinext_previousNextUrl";
function cloneHistoryState(state) {
	if (!state || typeof state !== "object") return {};
	const nextState = {};
	for (const [key, value] of Object.entries(state)) nextState[key] = value;
	return nextState;
}
function createHistoryStateWithPreviousNextUrl(state, previousNextUrl) {
	const nextState = cloneHistoryState(state);
	if (previousNextUrl === null) delete nextState[VINEXT_PREVIOUS_NEXT_URL_HISTORY_STATE_KEY];
	else nextState[VINEXT_PREVIOUS_NEXT_URL_HISTORY_STATE_KEY] = previousNextUrl;
	return Object.keys(nextState).length > 0 ? nextState : null;
}
function readHistoryStatePreviousNextUrl(state) {
	const value = cloneHistoryState(state)[VINEXT_PREVIOUS_NEXT_URL_HISTORY_STATE_KEY];
	return typeof value === "string" ? value : null;
}
function createOperationRecord(options) {
	return {
		id: options.id,
		lane: options.lane,
		startedVisibleCommitVersion: options.startedVisibleCommitVersion,
		state: "pending"
	};
}
function resolveInterceptionContextFromPreviousNextUrl(previousNextUrl, basePath = "") {
	if (previousNextUrl === null) return null;
	return stripBasePath(new URL(previousNextUrl, "http://localhost").pathname, basePath);
}
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
function resolveServerActionRequestState(options) {
	const headers = createRscRequestHeaders();
	headers.set(RSC_ACTION_HEADER, options.actionId);
	const interceptionContext = resolveInterceptionContextFromPreviousNextUrl(options.previousNextUrl, options.basePath);
	if (interceptionContext !== null) headers.set(VINEXT_INTERCEPTION_CONTEXT_HEADER, interceptionContext);
	const mountedSlotsHeader = getMountedSlotIdsHeader(options.elements);
	if (mountedSlotsHeader !== null) headers.set(VINEXT_MOUNTED_SLOTS_HEADER, mountedSlotsHeader);
	return { headers };
}
function resolvePendingNavigationCommitDispositionDecision(options) {
	const traceFields = createPendingNavigationTraceFields(options);
	if (options.startedNavigationId !== options.activeNavigationId || options.pending.action.operation.startedVisibleCommitVersion !== options.currentState.visibleCommitVersion) return {
		disposition: "skip",
		preserveElementIds: [],
		trace: createNavigationTrace(NavigationTraceReasonCodes.staleOperation, traceFields)
	};
	return mapNavigationDecisionToPendingDisposition(planPendingRootBoundaryFlightResponse({
		currentState: options.currentState,
		pending: options.pending,
		targetHref: options.targetHref,
		traceFields
	}));
}
function createPendingNavigationTraceFields(options) {
	return {
		...createNavigationLifecycleTraceFields({
			activeNavigationId: options.activeNavigationId,
			currentRootLayoutTreePath: options.currentState.rootLayoutTreePath,
			currentVisibleCommitVersion: options.currentState.visibleCommitVersion,
			nextRootLayoutTreePath: options.pending.rootLayoutTreePath,
			startedNavigationId: options.startedNavigationId,
			startedVisibleCommitVersion: options.pending.action.operation.startedVisibleCommitVersion
		}),
		...options.targetHref !== void 0 ? { targetHref: options.targetHref } : {}
	};
}
function createNavigationSnapshotUrl(snapshot) {
	const query = snapshot.searchParams.toString();
	return query === "" ? snapshot.pathname : `${snapshot.pathname}?${query}`;
}
function createMountedParallelSlotSnapshots(elements) {
	const snapshots = [];
	for (const slotId of getMountedSlotIds(elements)) {
		const parsed = AppElementsWire.parseElementKey(slotId);
		if (parsed?.kind !== "slot") continue;
		snapshots.push({
			ownerLayoutId: AppElementsWire.encodeLayoutId(parsed.treePath),
			slotId
		});
	}
	return snapshots;
}
function createVisibleRouteSnapshot(state) {
	return {
		displayUrl: createNavigationSnapshotUrl(state.navigationSnapshot),
		layoutIds: state.layoutIds,
		matchedUrl: state.navigationSnapshot.pathname,
		mountedParallelSlots: createMountedParallelSlotSnapshots(state.elements),
		rootBoundaryId: state.rootLayoutTreePath,
		routeId: state.routeId
	};
}
function createPendingRouteSnapshot(pending) {
	return {
		displayUrl: createNavigationSnapshotUrl(pending.action.navigationSnapshot),
		layoutIds: pending.action.layoutIds,
		matchedUrl: pending.action.navigationSnapshot.pathname,
		mountedParallelSlots: createMountedParallelSlotSnapshots(pending.action.elements),
		rootBoundaryId: pending.rootLayoutTreePath,
		routeId: pending.routeId
	};
}
function createPendingNavigationOperationToken(options) {
	return {
		baseVisibleCommitVersion: options.pending.action.operation.startedVisibleCommitVersion,
		deploymentVersion: null,
		graphVersion: null,
		lane: options.pending.action.operation.lane,
		operationId: options.pending.action.operation.id,
		targetSnapshotFingerprint: createRootBoundarySnapshotFingerprint(options.targetSnapshot)
	};
}
function createRootBoundarySnapshotFingerprint(snapshot) {
	return `${snapshot.routeId}|root:${snapshot.rootBoundaryId ?? "unknown"}`;
}
function planPendingRootBoundaryFlightResponse(options) {
	const targetSnapshot = createPendingRouteSnapshot(options.pending);
	const token = createPendingNavigationOperationToken({
		pending: options.pending,
		targetSnapshot
	});
	return navigationPlanner.plan({
		routeManifest: null,
		state: {
			nextOperationToken: token,
			traceFields: options.traceFields,
			visibleCommitVersion: options.currentState.visibleCommitVersion,
			visibleSnapshot: createVisibleRouteSnapshot(options.currentState)
		},
		event: {
			kind: "flightResponseArrived",
			result: {
				href: options.targetHref ?? targetSnapshot.displayUrl,
				targetSnapshot
			},
			token
		}
	});
}
function mapNavigationDecisionToPendingDisposition(decision) {
	switch (decision.kind) {
		case "proposeCommit": return {
			disposition: "dispatch",
			preserveAbsentSlots: decision.proposal.preserveAbsentSlots,
			preserveElementIds: decision.proposal.preserveElementIds,
			trace: decision.trace
		};
		case "hardNavigate": return {
			disposition: "hard-navigate",
			preserveElementIds: [],
			trace: decision.trace
		};
		case "noCommit": return {
			disposition: "skip",
			preserveElementIds: [],
			trace: decision.trace
		};
		case "requestWork": throw new Error(`[vinext] Root-boundary commit planning returned requestWork (${decision.work.kind}); flightResponseArrived should never request work`);
		default: throw new Error("[vinext] Unknown navigation decision: " + String(decision));
	}
}
async function createPendingNavigationCommit(options) {
	const elements = await options.nextElements;
	const metadata = AppElementsWire.readMetadata(elements);
	const previousNextUrl = options.previousNextUrl !== void 0 ? options.previousNextUrl : options.currentState.previousNextUrl;
	return {
		action: {
			elements,
			interceptionContext: metadata.interceptionContext,
			layoutIds: metadata.layoutIds,
			layoutFlags: metadata.layoutFlags,
			navigationSnapshot: options.navigationSnapshot,
			operation: createOperationRecord({
				id: options.renderId,
				lane: options.operationLane,
				startedVisibleCommitVersion: options.currentState.visibleCommitVersion
			}),
			previousNextUrl,
			renderId: options.renderId,
			rootLayoutTreePath: metadata.rootLayoutTreePath,
			routeId: metadata.routeId,
			type: options.type
		},
		interceptionContext: metadata.interceptionContext,
		previousNextUrl,
		rootLayoutTreePath: metadata.rootLayoutTreePath,
		routeId: metadata.routeId
	};
}
//#endregion
export { createHistoryStateWithPreviousNextUrl, createPendingNavigationCommit, readHistoryStatePreviousNextUrl, resolveInterceptionContextFromPreviousNextUrl, resolvePendingNavigationCommitDispositionDecision, resolveServerActionRequestState };

//# sourceMappingURL=app-browser-state.js.map