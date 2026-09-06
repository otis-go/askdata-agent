import { mergeElements } from "../shims/slot.js";
import { NavigationTraceReasonCodes, NavigationTraceTransactionCodes, createNavigationTrace, prependNavigationTraceEntry } from "./navigation-trace.js";
import { createPendingNavigationCommit, resolvePendingNavigationCommitDispositionDecision } from "./app-browser-state.js";
//#region src/server/app-browser-visible-commit.ts
const approvedVisibleCommitBrand = Symbol("ApprovedVisibleCommit");
function applyApprovedVisibleCommit(state, commit) {
	assertApprovedVisibleCommit(commit);
	return reduceApprovedVisibleCommitState(state, commit);
}
function assertApprovedVisibleCommit(commit) {
	if (commit[approvedVisibleCommitBrand] !== true) throw new Error("[vinext] Visible router state mutation requires ApprovedVisibleCommit");
}
function commitOperationRecord(operation, visibleCommitVersion) {
	return {
		id: operation.id,
		lane: operation.lane,
		startedVisibleCommitVersion: operation.startedVisibleCommitVersion,
		state: "committed",
		visibleCommitVersion
	};
}
function commitVisibleRouterState(state, nextState, operation) {
	const visibleCommitVersion = state.visibleCommitVersion + 1;
	return {
		...nextState,
		activeOperation: commitOperationRecord(operation, visibleCommitVersion),
		visibleCommitVersion
	};
}
function reduceApprovedVisibleCommitState(state, commit) {
	const { action } = commit;
	switch (action.type) {
		case "traverse":
		case "navigate": return commitVisibleRouterState(state, {
			elements: mergeElements(state.elements, action.elements, {
				clearAbsentSlots: action.type === "traverse",
				preserveAbsentSlots: commit.decision.preserveAbsentSlots,
				preserveElementIds: commit.decision.preserveElementIds
			}),
			interceptionContext: action.interceptionContext,
			layoutFlags: mergeLayoutFlags(state.layoutFlags, action.layoutFlags, commit.decision.preserveElementIds),
			layoutIds: action.layoutIds,
			navigationSnapshot: action.navigationSnapshot,
			previousNextUrl: action.previousNextUrl,
			renderId: action.renderId,
			rootLayoutTreePath: action.rootLayoutTreePath,
			routeId: action.routeId
		}, action.operation);
		case "replace": return commitVisibleRouterState(state, {
			elements: action.elements,
			interceptionContext: action.interceptionContext,
			layoutFlags: action.layoutFlags,
			layoutIds: action.layoutIds,
			navigationSnapshot: action.navigationSnapshot,
			previousNextUrl: action.previousNextUrl,
			renderId: action.renderId,
			rootLayoutTreePath: action.rootLayoutTreePath,
			routeId: action.routeId
		}, action.operation);
		default: {
			const _exhaustive = action.type;
			throw new Error("[vinext] Unknown router action: " + String(_exhaustive));
		}
	}
}
function resolvePendingNavigationCommitDecision(options) {
	const decision = resolvePendingNavigationCommitDispositionDecision(options);
	switch (decision.disposition) {
		case "skip": return {
			disposition: "no-commit",
			trace: decision.trace
		};
		case "hard-navigate": return {
			disposition: "hard-navigate",
			trace: decision.trace
		};
		case "dispatch": return createVisibleCommitDecision(decision.trace, decision.preserveElementIds, decision.preserveAbsentSlots);
		default: throw new Error("[vinext] Unknown navigation commit disposition: " + String(decision));
	}
}
function createVisibleCommitDecision(trace = createNavigationTrace(NavigationTraceReasonCodes.commitCurrent), preserveElementIds = [], preserveAbsentSlots = false) {
	return {
		disposition: "commit",
		preserveAbsentSlots,
		preserveElementIds: [...preserveElementIds],
		trace
	};
}
function mergeLayoutFlags(previousFlags, nextFlags, preserveElementIds) {
	const merged = { ...nextFlags };
	for (const id of preserveElementIds) {
		if (Object.hasOwn(merged, id)) continue;
		const value = previousFlags[id];
		if (value) merged[id] = value;
	}
	return merged;
}
function createApprovedVisibleCommit(options) {
	return {
		[approvedVisibleCommitBrand]: true,
		action: options.pending.action,
		decision: options.decision,
		interceptionContext: options.pending.interceptionContext,
		previousNextUrl: options.pending.previousNextUrl,
		rootLayoutTreePath: options.pending.rootLayoutTreePath,
		routeId: options.pending.routeId
	};
}
function createCommitTransactionFields(pending) {
	return {
		operationLane: pending.action.operation.lane,
		pendingOperationId: pending.action.operation.id,
		startedVisibleCommitVersion: pending.action.operation.startedVisibleCommitVersion
	};
}
function prependCommitTransactionTrace(trace, code, pending) {
	return prependNavigationTraceEntry(trace, code, createCommitTransactionFields(pending));
}
function addCommitTransactionTrace(decision, pending) {
	switch (decision.disposition) {
		case "commit": return {
			...decision,
			trace: prependCommitTransactionTrace(decision.trace, NavigationTraceTransactionCodes.visibleCommit, pending)
		};
		case "hard-navigate": return {
			...decision,
			trace: prependCommitTransactionTrace(decision.trace, NavigationTraceTransactionCodes.hardNavigate, pending)
		};
		case "no-commit": return {
			...decision,
			trace: prependCommitTransactionTrace(decision.trace, NavigationTraceTransactionCodes.noCommit, pending)
		};
		default: throw new Error("[vinext] Unknown commit decision: " + String(decision));
	}
}
function approveHmrVisibleCommit(pending) {
	if (pending.action.operation.lane !== "hmr") throw new Error("[vinext] HMR visible commit approval requires an HMR pending operation");
	const decision = addCommitTransactionTrace(createVisibleCommitDecision(), pending);
	if (decision.disposition !== "commit") throw new Error("[vinext] HMR visible commit approval did not produce a commit decision");
	return createApprovedVisibleCommit({
		decision,
		pending
	});
}
function approvePendingNavigationCommit(options) {
	const decision = addCommitTransactionTrace(resolvePendingNavigationCommitDecision({
		activeNavigationId: options.activeNavigationId,
		currentState: options.currentState,
		pending: options.pending,
		startedNavigationId: options.startedNavigationId,
		targetHref: options.targetHref
	}), options.pending);
	switch (decision.disposition) {
		case "commit": return {
			approvedCommit: createApprovedVisibleCommit({
				decision,
				pending: options.pending
			}),
			decision
		};
		case "hard-navigate":
		case "no-commit": return {
			approvedCommit: null,
			decision
		};
		default: throw new Error("[vinext] Unknown commit decision: " + String(decision));
	}
}
async function resolveAndClassifyNavigationCommit(options) {
	const pending = await createPendingNavigationCommit({
		currentState: options.currentState,
		nextElements: options.nextElements,
		navigationSnapshot: options.navigationSnapshot,
		operationLane: options.operationLane,
		previousNextUrl: options.previousNextUrl,
		renderId: options.renderId,
		type: options.type
	});
	const approvalState = options.getCurrentStateForApproval?.() ?? options.currentState;
	const approval = approvePendingNavigationCommit({
		activeNavigationId: options.getActiveNavigationId?.() ?? options.activeNavigationId,
		currentState: approvalState,
		pending,
		startedNavigationId: options.startedNavigationId,
		targetHref: options.targetHref
	});
	return {
		approvedCommit: approval.approvedCommit,
		decision: approval.decision,
		pending,
		trace: approval.decision.trace
	};
}
//#endregion
export { applyApprovedVisibleCommit, approveHmrVisibleCommit, approvePendingNavigationCommit, resolveAndClassifyNavigationCommit };

//# sourceMappingURL=app-browser-visible-commit.js.map