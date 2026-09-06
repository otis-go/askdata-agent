import { NavigationTraceReasonCodes, createNavigationLifecycleTraceFields, createNavigationTrace } from "./navigation-trace.js";
//#region src/server/navigation-planner.ts
function createRequestWorkDecision(options) {
	return {
		kind: "requestWork",
		token: options.state.nextOperationToken,
		work: options.work,
		trace: createNavigationTrace(NavigationTraceReasonCodes.requestWork, {
			eventKind: options.eventKind,
			targetHref: getRequestedWorkTargetHref(options.work)
		})
	};
}
function getRequestedWorkTargetHref(work) {
	switch (work.kind) {
		case "flight":
		case "prefetch": return work.href;
		case "traverseFlight": return null;
		default: throw new Error("[vinext] Unknown requested navigation work: " + String(work));
	}
}
function createRootBoundaryTraceFields(options) {
	return options.state.traceFields ?? createNavigationLifecycleTraceFields({
		currentRootLayoutTreePath: options.state.visibleSnapshot.rootBoundaryId,
		currentVisibleCommitVersion: options.state.visibleCommitVersion,
		nextRootLayoutTreePath: options.event.result.targetSnapshot.rootBoundaryId,
		startedVisibleCommitVersion: options.event.token.baseVisibleCommitVersion
	});
}
function classifyRootBoundaryTransition(currentRootBoundaryId, nextRootBoundaryId) {
	if (currentRootBoundaryId === null || nextRootBoundaryId === null) return "rootBoundaryUnknownFallback";
	return currentRootBoundaryId === nextRootBoundaryId ? "currentRootBoundary" : "rootBoundaryChanged";
}
function resolveSameLayoutAncestorPersistence(currentSnapshot, targetSnapshot) {
	if (classifyRootBoundaryTransition(currentSnapshot.rootBoundaryId, targetSnapshot.rootBoundaryId) !== "currentRootBoundary") return [];
	const commonLayoutIds = [];
	const maxLength = Math.min(currentSnapshot.layoutIds.length, targetSnapshot.layoutIds.length);
	for (let index = 0; index < maxLength; index++) {
		const layoutId = currentSnapshot.layoutIds[index];
		if (layoutId !== targetSnapshot.layoutIds[index]) break;
		commonLayoutIds.push(layoutId);
	}
	return commonLayoutIds;
}
function resolveMountedParallelSlotPersistence(currentSnapshot, targetSnapshot) {
	return resolveMountedParallelSlotPersistenceForLayouts(currentSnapshot, resolveSameLayoutAncestorPersistence(currentSnapshot, targetSnapshot));
}
function resolveMountedParallelSlotPersistenceForLayouts(currentSnapshot, preservedLayoutIds) {
	if (preservedLayoutIds.length === 0) return [];
	const preservedLayoutIdSet = new Set(preservedLayoutIds);
	const preservedSlotIds = [];
	const seenSlotIds = /* @__PURE__ */ new Set();
	for (const slot of currentSnapshot.mountedParallelSlots) {
		if (slot.ownerLayoutId === null) continue;
		if (!preservedLayoutIdSet.has(slot.ownerLayoutId)) continue;
		if (seenSlotIds.has(slot.slotId)) continue;
		preservedSlotIds.push(slot.slotId);
		seenSlotIds.add(slot.slotId);
	}
	return preservedSlotIds;
}
function resolveCurrentRootBoundaryElementPersistence(currentSnapshot, targetSnapshot) {
	const preservedLayoutIds = resolveSameLayoutAncestorPersistence(currentSnapshot, targetSnapshot);
	return [...preservedLayoutIds, ...resolveMountedParallelSlotPersistenceForLayouts(currentSnapshot, preservedLayoutIds)];
}
function resolveCurrentRootBoundaryCommitElementPersistence(options) {
	const preservedLayoutIds = resolveSameLayoutAncestorPersistence(options.currentSnapshot, options.targetSnapshot);
	if (options.lane === "traverse") return preservedLayoutIds;
	return [...preservedLayoutIds, ...resolveMountedParallelSlotPersistenceForLayouts(options.currentSnapshot, preservedLayoutIds)];
}
function planFlightResponseArrived(options) {
	const traceFields = createRootBoundaryTraceFields(options);
	if (options.event.token.lane === "prefetch") return {
		kind: "noCommit",
		reason: "prefetchOnly",
		token: options.event.token,
		trace: createNavigationTrace(NavigationTraceReasonCodes.prefetchOnly, traceFields)
	};
	const transition = classifyRootBoundaryTransition(options.state.visibleSnapshot.rootBoundaryId, options.event.result.targetSnapshot.rootBoundaryId);
	if (transition === "rootBoundaryChanged") return {
		kind: "hardNavigate",
		reason: "rootBoundaryChanged",
		token: options.event.token,
		trace: createNavigationTrace(NavigationTraceReasonCodes.rootBoundaryChanged, traceFields),
		url: options.event.result.href
	};
	if (transition === "rootBoundaryUnknownFallback") return {
		kind: "proposeCommit",
		proposal: {
			preserveAbsentSlots: true,
			preserveElementIds: [],
			reason: "rootBoundaryUnknownFallback",
			targetSnapshot: options.event.result.targetSnapshot
		},
		token: options.event.token,
		trace: createNavigationTrace(NavigationTraceReasonCodes.rootBoundaryUnknown, traceFields)
	};
	return {
		kind: "proposeCommit",
		proposal: {
			preserveAbsentSlots: false,
			preserveElementIds: resolveCurrentRootBoundaryCommitElementPersistence({
				currentSnapshot: options.state.visibleSnapshot,
				lane: options.event.token.lane,
				targetSnapshot: options.event.result.targetSnapshot
			}),
			reason: "currentRootBoundary",
			targetSnapshot: options.event.result.targetSnapshot
		},
		token: options.event.token,
		trace: createNavigationTrace(NavigationTraceReasonCodes.commitCurrent, traceFields)
	};
}
function planNavigation(input) {
	switch (input.event.kind) {
		case "navigate": return createRequestWorkDecision({
			eventKind: input.event.kind,
			state: input.state,
			work: {
				href: input.event.href,
				kind: "flight",
				mode: input.event.mode
			}
		});
		case "refresh": return createRequestWorkDecision({
			eventKind: input.event.kind,
			state: input.state,
			work: {
				href: input.state.visibleSnapshot.displayUrl,
				kind: "flight",
				mode: "refresh"
			}
		});
		case "traverse": return createRequestWorkDecision({
			eventKind: input.event.kind,
			state: input.state,
			work: {
				direction: input.event.direction,
				historyState: input.event.historyState,
				kind: "traverseFlight"
			}
		});
		case "prefetch": return createRequestWorkDecision({
			eventKind: input.event.kind,
			state: input.state,
			work: {
				href: input.event.href,
				kind: "prefetch"
			}
		});
		case "flightResponseArrived": return planFlightResponseArrived({
			event: input.event,
			state: input.state
		});
		default: {
			const _exhaustive = input.event;
			throw new Error("[vinext] Unknown navigation event: " + String(_exhaustive));
		}
	}
}
const navigationPlanner = {
	classifyRootBoundaryTransition,
	plan: planNavigation,
	resolveCurrentRootBoundaryElementPersistence,
	resolveMountedParallelSlotPersistence,
	resolveSameLayoutAncestorPersistence
};
//#endregion
export { navigationPlanner };

//# sourceMappingURL=navigation-planner.js.map