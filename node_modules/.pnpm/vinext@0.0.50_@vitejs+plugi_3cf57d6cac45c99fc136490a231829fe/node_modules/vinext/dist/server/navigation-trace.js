//#region src/server/navigation-trace.ts
const NAVIGATION_TRACE_SCHEMA_VERSION = 0;
const NavigationTraceReasonCodes = {
	commitCurrent: "NC_COMMIT",
	prefetchOnly: "NC_PREFETCH_ONLY",
	requestWork: "NC_REQUEST",
	rootBoundaryChanged: "NC_ROOT",
	rootBoundaryUnknown: "NC_ROOT_UNKNOWN",
	staleOperation: "NC_STALE"
};
const NavigationTraceTransactionCodes = {
	hardNavigate: "NT_HARD_NAVIGATE",
	noCommit: "NT_NO_COMMIT",
	visibleCommit: "NT_VISIBLE_COMMIT"
};
function createNavigationLifecycleTraceFields(options) {
	return {
		...options.activeNavigationId !== void 0 ? { activeNavigationId: options.activeNavigationId } : {},
		currentRootLayoutTreePath: options.currentRootLayoutTreePath,
		currentVisibleCommitVersion: options.currentVisibleCommitVersion,
		nextRootLayoutTreePath: options.nextRootLayoutTreePath,
		...options.startedNavigationId !== void 0 ? { startedNavigationId: options.startedNavigationId } : {},
		startedVisibleCommitVersion: options.startedVisibleCommitVersion
	};
}
function createNavigationTraceEntry(code, fields = {}) {
	return {
		code,
		fields: { ...fields }
	};
}
function createNavigationTrace(code, fields = {}) {
	return {
		schemaVersion: 0,
		entries: [createNavigationTraceEntry(code, fields)]
	};
}
function prependNavigationTraceEntry(trace, code, fields = {}) {
	return {
		schemaVersion: trace.schemaVersion,
		entries: [createNavigationTraceEntry(code, fields), ...trace.entries]
	};
}
//#endregion
export { NAVIGATION_TRACE_SCHEMA_VERSION, NavigationTraceReasonCodes, NavigationTraceTransactionCodes, createNavigationLifecycleTraceFields, createNavigationTrace, prependNavigationTraceEntry };

//# sourceMappingURL=navigation-trace.js.map