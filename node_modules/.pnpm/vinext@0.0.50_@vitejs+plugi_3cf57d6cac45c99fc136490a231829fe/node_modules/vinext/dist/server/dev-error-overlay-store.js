//#region src/server/dev-error-overlay-store.ts
const MAX_DEV_OVERLAY_ERRORS = 50;
let snapshot = {
	errors: [],
	index: 0,
	minimized: false
};
const listeners = /* @__PURE__ */ new Set();
function emit() {
	for (const fn of listeners) fn();
}
function subscribeOverlay(fn) {
	listeners.add(fn);
	return () => {
		listeners.delete(fn);
	};
}
function getOverlaySnapshot() {
	return snapshot;
}
function reportToOverlay(error) {
	const next = [...snapshot.errors, error];
	const dropped = next.length > MAX_DEV_OVERLAY_ERRORS ? next.length - MAX_DEV_OVERLAY_ERRORS : 0;
	const errors = dropped > 0 ? next.slice(dropped) : next;
	snapshot = {
		errors,
		index: errors.length - 1,
		minimized: false
	};
	emit();
}
function dismissOverlay() {
	snapshot = {
		errors: [],
		index: 0,
		minimized: false
	};
	emit();
}
function setOverlayIndex(index) {
	if (index < 0 || index >= snapshot.errors.length) return;
	snapshot = {
		...snapshot,
		index
	};
	emit();
}
function minimizeOverlay() {
	if (snapshot.minimized) return;
	snapshot = {
		...snapshot,
		minimized: true
	};
	emit();
}
function expandOverlay() {
	if (!snapshot.minimized) return;
	snapshot = {
		...snapshot,
		minimized: false
	};
	emit();
}
//#endregion
export { dismissOverlay, expandOverlay, getOverlaySnapshot, minimizeOverlay, reportToOverlay, setOverlayIndex, subscribeOverlay };

//# sourceMappingURL=dev-error-overlay-store.js.map