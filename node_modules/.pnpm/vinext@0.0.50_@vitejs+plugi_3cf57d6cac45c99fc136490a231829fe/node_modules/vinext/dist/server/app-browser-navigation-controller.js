import { activateNavigationSnapshot, clearPendingPathname, commitClientNavigationState } from "../shims/navigation.js";
import { createPendingNavigationCommit } from "./app-browser-state.js";
import { applyApprovedVisibleCommit, approveHmrVisibleCommit, approvePendingNavigationCommit, resolveAndClassifyNavigationCommit } from "./app-browser-visible-commit.js";
import { startTransition, useLayoutEffect } from "react";
//#region src/server/app-browser-navigation-controller.ts
const HARD_NAVIGATION_LOOP_GUARD_KEY = "__vinext_hard_navigation_target__";
function normalizeBrowserHref(href) {
	try {
		return new URL(href, window.location.href).href;
	} catch {
		return href;
	}
}
function readHardNavigationLoopGuard() {
	try {
		return window.sessionStorage.getItem(HARD_NAVIGATION_LOOP_GUARD_KEY);
	} catch {
		return null;
	}
}
function writeHardNavigationLoopGuard(targetHref) {
	try {
		window.sessionStorage.setItem(HARD_NAVIGATION_LOOP_GUARD_KEY, targetHref);
		return window.sessionStorage.getItem(HARD_NAVIGATION_LOOP_GUARD_KEY) === targetHref;
	} catch {
		return false;
	}
}
function clearHardNavigationLoopGuard() {
	try {
		window.sessionStorage.removeItem(HARD_NAVIGATION_LOOP_GUARD_KEY);
	} catch {}
}
function performHardNavigationWithLoopGuard(href, mode = "assign") {
	const targetHref = normalizeBrowserHref(href);
	const currentHref = normalizeBrowserHref(window.location.href);
	if (readHardNavigationLoopGuard() === targetHref && currentHref === targetHref) {
		clearHardNavigationLoopGuard();
		console.error(`[vinext] Prevented repeated hard navigation to ${targetHref}; leaving the current document in place to avoid a reload loop.`);
		return false;
	}
	if (!writeHardNavigationLoopGuard(targetHref) && currentHref === targetHref) {
		console.error(`[vinext] Hard navigation to ${targetHref} requires a reload-loop guard, but sessionStorage is unavailable; leaving the current document in place.`);
		return false;
	}
	if (mode === "replace") window.location.replace(href);
	else window.location.assign(href);
	return true;
}
function createAppBrowserNavigationController(deps = {}) {
	const commitClientNavigationStateImpl = deps.commitClientNavigationState ?? commitClientNavigationState;
	const performHardNavigation = deps.performHardNavigation ?? performHardNavigationWithLoopGuard;
	let nextNavigationRenderId = 0;
	let activeNavigationId = 0;
	const pendingNavigationCommits = /* @__PURE__ */ new Map();
	const pendingNavigationPrePaintEffects = /* @__PURE__ */ new Map();
	let setBrowserRouterState = null;
	let browserRouterStateRef = null;
	let activePendingBrowserRouterState = null;
	let resolveBrowserRouterStateReady = null;
	let browserRouterStateReadyPromise = null;
	let browserRouterStateHasCommitted = false;
	function getBrowserRouterStateSetter() {
		if (!setBrowserRouterState) throw new Error("[vinext] Browser router state setter is not initialized");
		return setBrowserRouterState;
	}
	function getBrowserRouterState() {
		if (!browserRouterStateRef) throw new Error("[vinext] Browser router state is not initialized");
		return browserRouterStateRef.current;
	}
	function waitForBrowserRouterStateReady() {
		if (browserRouterStateRef || browserRouterStateHasCommitted) return Promise.resolve();
		if (!browserRouterStateReadyPromise) browserRouterStateReadyPromise = new Promise((resolve) => {
			resolveBrowserRouterStateReady = resolve;
		});
		return browserRouterStateReadyPromise;
	}
	function markBrowserRouterStateReady() {
		browserRouterStateHasCommitted = true;
		const resolveReady = resolveBrowserRouterStateReady;
		resolveBrowserRouterStateReady = null;
		browserRouterStateReadyPromise = null;
		resolveReady?.();
	}
	function beginNavigation() {
		activeNavigationId += 1;
		return activeNavigationId;
	}
	function allocateRenderId() {
		nextNavigationRenderId += 1;
		return nextNavigationRenderId;
	}
	function hasBrowserRouterState() {
		return browserRouterStateRef !== null;
	}
	function isCurrentNavigation(navId) {
		return navId === activeNavigationId;
	}
	function beginPendingBrowserRouterState() {
		const setter = getBrowserRouterStateSetter();
		if (activePendingBrowserRouterState && !activePendingBrowserRouterState.settled) {
			activePendingBrowserRouterState.settled = true;
			activePendingBrowserRouterState.resolve(getBrowserRouterState());
		}
		let resolvePending;
		const promise = new Promise((resolve) => {
			resolvePending = resolve;
		});
		if (!resolvePending) throw new Error("[vinext] Failed to initialize browser router promise");
		const pending = {
			promise,
			resolve: resolvePending,
			settled: false
		};
		activePendingBrowserRouterState = pending;
		setter(promise);
		return pending;
	}
	function settlePendingBrowserRouterState(pending) {
		if (!pending || pending.settled) return;
		pending.settled = true;
		pending.resolve(getBrowserRouterState());
		if (activePendingBrowserRouterState === pending) activePendingBrowserRouterState = null;
	}
	function finalizeNavigation(navId, pending) {
		settlePendingBrowserRouterState(pending);
		if (isCurrentNavigation(navId)) clearPendingPathname(navId);
	}
	function resolvePendingBrowserRouterState(pending, commit) {
		if (!pending || pending.settled) return;
		pending.settled = true;
		pending.resolve(applyApprovedVisibleCommit(getBrowserRouterState(), commit));
		if (activePendingBrowserRouterState === pending) activePendingBrowserRouterState = null;
	}
	function queuePrePaintNavigationEffect(renderId, effect) {
		if (!effect) return;
		pendingNavigationPrePaintEffects.set(renderId, effect);
	}
	/**
	* Run all queued pre-paint effects for renderIds up to and including the
	* given renderId. When React supersedes a startTransition update (rapid
	* clicks on same-route links), the superseded NavigationCommitSignal never
	* mounts, so its pre-paint effect never fires. By draining all effects
	* <= the committed renderId here, the winning transition cleans up after
	* any superseded ones, keeping the counter balanced.
	*
	* Invariant: each superseded navigation gets a commitClientNavigationState()
	* to balance the activateNavigationSnapshot() from its renderNavigationPayload call.
	*/
	function drainPrePaintEffects(upToRenderId) {
		for (const [id, effect] of pendingNavigationPrePaintEffects) {
			if (id > upToRenderId) continue;
			pendingNavigationPrePaintEffects.delete(id);
			if (id === upToRenderId) effect();
			else commitClientNavigationStateImpl(void 0, { releaseSnapshot: true });
		}
	}
	/**
	* Resolve all pending navigation commits with renderId <= the committed renderId.
	* Note: Map iteration handles concurrent deletion safely — entries are visited in
	* insertion order and deletion doesn't affect the iterator's view of remaining entries.
	* This pattern is also used in drainPrePaintEffects with the same semantics.
	*/
	function resolveCommittedNavigations(renderId) {
		for (const [pendingId, resolve] of pendingNavigationCommits) {
			if (pendingId > renderId) continue;
			pendingNavigationCommits.delete(pendingId);
			resolve();
		}
	}
	async function hmrReplaceTree(nextElements, navigationSnapshot) {
		if (!hasBrowserRouterState()) return;
		const pending = await createPendingNavigationCommit({
			currentState: getBrowserRouterState(),
			nextElements,
			navigationSnapshot,
			operationLane: "hmr",
			renderId: allocateRenderId(),
			type: "replace"
		});
		if (!hasBrowserRouterState()) return;
		dispatchSynchronousVisibleCommit(approveHmrVisibleCommit(pending));
	}
	function NavigationCommitSignal({ renderId, children }) {
		useLayoutEffect(() => {
			drainPrePaintEffects(renderId);
			const frame = requestAnimationFrame(() => {
				resolveCommittedNavigations(renderId);
			});
			return () => {
				cancelAnimationFrame(frame);
				resolveCommittedNavigations(renderId);
			};
		}, [renderId]);
		return children;
	}
	function dispatchApprovedVisibleCommit(commit, pendingRouterState) {
		const setter = getBrowserRouterStateSetter();
		if (pendingRouterState) {
			resolvePendingBrowserRouterState(pendingRouterState, commit);
			return;
		}
		startTransition(() => {
			setter(applyApprovedVisibleCommit(getBrowserRouterState(), commit));
		});
	}
	function dispatchSynchronousVisibleCommit(commit) {
		getBrowserRouterStateSetter()(applyApprovedVisibleCommit(getBrowserRouterState(), commit));
	}
	async function renderNavigationPayload(options) {
		const renderId = allocateRenderId();
		let resolveCommitted;
		const committed = new Promise((resolve) => {
			resolveCommitted = resolve;
			pendingNavigationCommits.set(renderId, resolve);
		});
		let snapshotActivated = false;
		try {
			const pending = await createPendingNavigationCommit({
				currentState: getBrowserRouterState(),
				nextElements: options.nextElements,
				navigationSnapshot: options.navigationSnapshot,
				operationLane: options.operationLane,
				previousNextUrl: options.previousNextUrl,
				renderId,
				type: options.actionType
			});
			const approval = approvePendingNavigationCommit({
				activeNavigationId,
				currentState: getBrowserRouterState(),
				pending,
				startedNavigationId: options.navId,
				targetHref: options.targetHref
			});
			if (approval.decision.disposition === "no-commit") {
				settlePendingBrowserRouterState(options.pendingRouterState);
				pendingNavigationCommits.delete(renderId);
				resolveCommitted?.();
				return "no-commit";
			}
			if (approval.decision.disposition === "hard-navigate") {
				settlePendingBrowserRouterState(options.pendingRouterState);
				pendingNavigationCommits.delete(renderId);
				return performHardNavigation(options.targetHref) ? "hard-navigate" : "no-commit";
			}
			const approvedCommit = approval.approvedCommit;
			if (approvedCommit === null) throw new Error("[vinext] Commit decision did not approve a visible commit");
			queuePrePaintNavigationEffect(renderId, options.createNavigationCommitEffect({
				href: options.targetHref,
				historyUpdateMode: options.historyUpdateMode,
				navId: options.navId,
				params: options.params,
				previousNextUrl: approvedCommit.previousNextUrl
			}));
			activateNavigationSnapshot();
			snapshotActivated = true;
			dispatchApprovedVisibleCommit(approvedCommit, options.pendingRouterState);
		} catch (error) {
			pendingNavigationPrePaintEffects.delete(renderId);
			pendingNavigationCommits.delete(renderId);
			if (snapshotActivated) commitClientNavigationStateImpl(options.navId);
			settlePendingBrowserRouterState(options.pendingRouterState);
			resolveCommitted?.();
			throw error;
		}
		return committed.then(() => "committed");
	}
	async function commitSameUrlNavigatePayload(nextElements, navigationSnapshot, returnValue, actionInitiationState) {
		const currentState = actionInitiationState ?? getBrowserRouterState();
		const startedNavigationId = activeNavigationId;
		const { approvedCommit, decision, pending, trace: _navigationTrace } = await resolveAndClassifyNavigationCommit({
			activeNavigationId,
			currentState,
			getActiveNavigationId: () => activeNavigationId,
			getCurrentStateForApproval: getBrowserRouterState,
			navigationSnapshot,
			nextElements,
			renderId: allocateRenderId(),
			operationLane: "server-action",
			startedNavigationId,
			targetHref: window.location.href,
			type: "navigate"
		});
		if (decision.disposition === "hard-navigate") {
			performHardNavigation(window.location.href);
			return;
		}
		if (approvedCommit) {
			const latestApproval = approvePendingNavigationCommit({
				activeNavigationId,
				currentState: getBrowserRouterState(),
				pending,
				startedNavigationId,
				targetHref: window.location.href
			});
			if (latestApproval.decision.disposition === "hard-navigate") {
				performHardNavigation(window.location.href);
				return;
			}
			if (latestApproval.approvedCommit) dispatchSynchronousVisibleCommit(latestApproval.approvedCommit);
		}
		if (returnValue) {
			if (!returnValue.ok) throw returnValue.data;
			return returnValue.data;
		}
	}
	function attachBrowserRouterState(setter, stateRef) {
		setBrowserRouterState = setter;
		browserRouterStateRef = stateRef;
		markBrowserRouterStateReady();
		return () => {
			if (setBrowserRouterState === setter) setBrowserRouterState = null;
			if (browserRouterStateRef === stateRef) {
				browserRouterStateRef = null;
				browserRouterStateHasCommitted = false;
			}
		};
	}
	return {
		beginNavigation,
		hasBrowserRouterState,
		getBrowserRouterState,
		isCurrentNavigation,
		waitForBrowserRouterStateReady,
		attachBrowserRouterState,
		beginPendingBrowserRouterState,
		finalizeNavigation,
		renderNavigationPayload,
		commitSameUrlNavigatePayload,
		hmrReplaceTree,
		drainPrePaintEffects,
		NavigationCommitSignal
	};
}
//#endregion
export { clearHardNavigationLoopGuard, createAppBrowserNavigationController };

//# sourceMappingURL=app-browser-navigation-controller.js.map