//#region src/server/navigation-trace.d.ts
declare const NAVIGATION_TRACE_SCHEMA_VERSION = 0;
type NavigationTraceSchemaVersion = 0;
declare const NavigationTraceReasonCodes: {
  commitCurrent: "NC_COMMIT";
  prefetchOnly: "NC_PREFETCH_ONLY";
  requestWork: "NC_REQUEST";
  rootBoundaryChanged: "NC_ROOT";
  rootBoundaryUnknown: "NC_ROOT_UNKNOWN";
  staleOperation: "NC_STALE";
};
declare const NavigationTraceTransactionCodes: {
  hardNavigate: "NT_HARD_NAVIGATE";
  noCommit: "NT_NO_COMMIT";
  visibleCommit: "NT_VISIBLE_COMMIT";
};
type NavigationTraceReasonCode = (typeof NavigationTraceReasonCodes)[keyof typeof NavigationTraceReasonCodes];
type NavigationTraceTransactionCode = (typeof NavigationTraceTransactionCodes)[keyof typeof NavigationTraceTransactionCodes];
type NavigationTraceCode = NavigationTraceReasonCode | NavigationTraceTransactionCode;
type NavigationTraceFieldName = "activeNavigationId" | "currentRootLayoutTreePath" | "currentVisibleCommitVersion" | "nextRootLayoutTreePath" | "eventKind" | "operationLane" | "pendingOperationId" | "startedVisibleCommitVersion" | "startedNavigationId" | "targetHref";
type NavigationTraceFieldValue = string | number | boolean | null;
type NavigationTraceFields = Readonly<Partial<Record<NavigationTraceFieldName, NavigationTraceFieldValue>>>;
type NavigationTraceEntry = Readonly<{
  code: NavigationTraceCode;
  fields: NavigationTraceFields;
}>;
type NavigationTrace = Readonly<{
  schemaVersion: NavigationTraceSchemaVersion;
  entries: readonly NavigationTraceEntry[];
}>;
declare function createNavigationLifecycleTraceFields(options: {
  activeNavigationId?: number;
  currentRootLayoutTreePath: string | null;
  currentVisibleCommitVersion: number;
  nextRootLayoutTreePath: string | null;
  startedNavigationId?: number;
  startedVisibleCommitVersion: number;
}): NavigationTraceFields;
declare function createNavigationTrace(code: NavigationTraceCode, fields?: NavigationTraceFields): NavigationTrace;
declare function prependNavigationTraceEntry(trace: NavigationTrace, code: NavigationTraceCode, fields?: NavigationTraceFields): NavigationTrace;
//#endregion
export { NAVIGATION_TRACE_SCHEMA_VERSION, NavigationTrace, NavigationTraceCode, NavigationTraceEntry, NavigationTraceFieldName, NavigationTraceFieldValue, NavigationTraceFields, NavigationTraceReasonCode, NavigationTraceReasonCodes, NavigationTraceSchemaVersion, NavigationTraceTransactionCode, NavigationTraceTransactionCodes, createNavigationLifecycleTraceFields, createNavigationTrace, prependNavigationTraceEntry };
//# sourceMappingURL=navigation-trace.d.ts.map