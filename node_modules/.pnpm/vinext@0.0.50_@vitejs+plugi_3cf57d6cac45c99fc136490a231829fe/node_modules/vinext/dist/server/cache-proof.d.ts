import { AppRouteSemanticIds } from "../routing/app-route-graph.js";

//#region src/server/cache-proof.d.ts
declare const CACHE_PROOF_MODEL_SCHEMA_VERSION = 0;
type CacheProofModelSchemaVersion = 0;
type CacheProofRejectionCode = "CP_MODEL_DISABLED" | "CP_DIMENSION_COUNT_EXCEEDED" | "CP_DIMENSION_NAME_MISSING" | "CP_DIMENSION_NAME_TOO_LONG" | "CP_DIMENSION_VALUE_COUNT_EXCEEDED" | "CP_DIMENSION_VALUE_TOO_LONG" | "CP_DIMENSION_VALUES_MISSING" | "CP_ENCODED_VARIANT_TOO_LONG" | "CP_INVALID_VARIANT_BUDGET" | "CP_ROUTE_VARIANT_CEILING_EXCEEDED" | "CP_UNSAFE_PUBLIC_DIMENSION" | "CP_BOUNDARY_OUTCOME_MISMATCH" | "CP_BOUNDARY_OUTCOME_UNKNOWN";
type CacheProofTraceFieldValue = string | number | boolean | null | readonly string[];
type CacheProofTraceFields = Readonly<Record<string, CacheProofTraceFieldValue>>;
type CacheProofBreakerFallbackMode = "renderFresh" | "privateUncacheable";
type CacheProofFallbackScope = "affectedOutput" | "route";
type CacheProofBreakerFallback = Readonly<{
  kind: "breakerFallback";
  code: CacheProofRejectionCode;
  mode: CacheProofBreakerFallbackMode;
  scope: CacheProofFallbackScope;
  fields: CacheProofTraceFields;
}>;
type CacheVariantBudget = Readonly<{
  maxDimensionCount: number;
  maxDimensionNameLength: number;
  maxDimensionValueLength: number;
  maxEncodedLength: number;
  maxValuesPerDimension: number;
  maxVariantsPerRoute: number;
}>;
declare const DEFAULT_CACHE_VARIANT_BUDGET: {
  maxDimensionCount: number;
  maxDimensionNameLength: number;
  maxDimensionValueLength: number;
  maxEncodedLength: number;
  maxValuesPerDimension: number;
  maxVariantsPerRoute: number;
};
type CacheVariantDimensionSource = "auth" | "cookie" | "custom" | "draft-mode" | "header" | "interception" | "mounted-slots" | "params" | "route" | "search" | "session";
type CacheVariantDimensionPrivacy = "internal" | "private" | "public";
type CacheVariantDimensionInput = Readonly<{
  name: string;
  privacy: CacheVariantDimensionPrivacy;
  source: CacheVariantDimensionSource;
  values: readonly string[];
}>;
type CacheVariantDimension = Readonly<{
  encoded: string;
  name: string;
  privacy: CacheVariantDimensionPrivacy;
  source: CacheVariantDimensionSource;
  valueCount: number;
  valueHashes: readonly string[];
}>;
type CacheProofOutputScope = Readonly<{
  kind: "app-html";
  renderEpoch: string | null;
  rootBoundaryId: string | null;
  routeId: string;
}> | Readonly<{
  kind: "app-rsc";
  mountedSlotsFingerprint: string | null;
  renderEpoch: string | null;
  rootBoundaryId: string | null;
  routeId: string;
}> | Readonly<{
  kind: "layout";
  layoutId: string;
  rootBoundaryId: string | null;
  routeId: string;
}> | Readonly<{
  kind: "page";
  pageId: string;
  rootBoundaryId: string | null;
  routeId: string;
}> | Readonly<{
  kind: "route-handler";
  routeHandlerId: string;
  routeId: string;
}> | Readonly<{
  kind: "slot";
  rootBoundaryId: string | null;
  routeId: string;
  slotId: string;
}> | Readonly<{
  kind: "template";
  rootBoundaryId: string | null;
  routeId: string;
  templateId: string;
}>;
type CacheVariant = Readonly<{
  budget: CacheVariantBudget;
  cacheKey: string;
  dimensions: readonly CacheVariantDimension[];
  encodedLength: number;
  output: CacheProofOutputScope;
  schemaVersion: CacheProofModelSchemaVersion;
}>;
type BuildCacheVariantInput = Readonly<{
  budget: CacheVariantBudget;
  dimensions: readonly CacheVariantDimensionInput[];
  existingVariantCount: number;
  output: CacheProofOutputScope;
}>;
type BuildCacheVariantResult = Readonly<{
  kind: "variant";
  variant: CacheVariant;
}> | Readonly<{
  kind: "breakerFallback";
  fallback: CacheProofBreakerFallback;
}>;
type AppRouteCacheProofGraphScopeInput = Readonly<{
  ids: AppRouteSemanticIds;
}>;
type AppRouteCacheProofGraphScope = Readonly<{
  layoutIds: readonly string[];
  pageId: string | null;
  routeHandlerId: string | null;
  routeId: string;
  slotIds: readonly string[];
  templateIds: readonly string[];
}>;
type BoundaryOutcome = Readonly<{
  kind: "error";
  digest?: string;
}> | Readonly<{
  kind: "forbidden";
}> | Readonly<{
  kind: "globalError";
  digest?: string;
}> | Readonly<{
  kind: "notFound";
}> | Readonly<{
  kind: "redirect";
  location: string;
  status: number;
}> | Readonly<{
  kind: "success";
}> | Readonly<{
  kind: "unauthorized";
}> | Readonly<{
  kind: "unknown";
}>;
type BoundaryOutcomeCompatibility = Readonly<{
  kind: "compatible";
  outcome: BoundaryOutcome;
  reason: "CP_BOUNDARY_OUTCOME_MATCH";
}> | Readonly<{
  candidate: BoundaryOutcome;
  expected: BoundaryOutcome;
  fallback: CacheProofBreakerFallback;
  kind: "incompatible";
}>;
type RenderObservationCompleteness = "complete" | "partial" | "unknown";
type RenderCacheability = "private" | "public" | "uncacheable" | "unknown";
type RenderRequestApiKind = "connection" | "cookies" | "draftMode" | "headers" | "params" | "searchParams";
type RenderRequestApiStatus = "notObserved" | "observed" | "unknown";
type RenderRequestApiObservation = Readonly<{
  kind: RenderRequestApiKind;
  status: RenderRequestApiStatus;
}>;
type RenderObservation = Readonly<{
  boundaryOutcome: BoundaryOutcome;
  cacheTags: readonly string[];
  cacheability: RenderCacheability;
  completeness: RenderObservationCompleteness;
  dynamicFetches: readonly string[];
  output: CacheProofOutputScope;
  pathTags: readonly string[];
  requestApis: readonly RenderRequestApiObservation[];
  schemaVersion: CacheProofModelSchemaVersion;
}>;
type BuildRenderObservationInput = Readonly<{
  boundaryOutcome: BoundaryOutcome;
  cacheTags: readonly string[];
  cacheability: RenderCacheability;
  completeness: RenderObservationCompleteness;
  dynamicFetches: readonly string[];
  output: CacheProofOutputScope;
  pathTags: readonly string[];
  requestApis: readonly RenderRequestApiObservation[];
}>;
type DisabledCacheProofDecision = Readonly<{
  canReuse: false;
  fallback: CacheProofBreakerFallback;
  kind: "disabled";
  observation: RenderObservation;
  variant: CacheVariant;
}>;
type CreateDisabledCacheProofDecisionInput = Readonly<{
  observation: RenderObservation;
  variant: CacheVariant;
}>;
declare function createAppRouteCacheProofGraphScope(route: AppRouteCacheProofGraphScopeInput): AppRouteCacheProofGraphScope;
declare function buildCacheVariant(input: BuildCacheVariantInput): BuildCacheVariantResult;
declare function buildBoundaryOutcomeCompatibility(input: {
  candidate: BoundaryOutcome;
  expected: BoundaryOutcome;
}): BoundaryOutcomeCompatibility;
declare function buildRenderObservation(input: BuildRenderObservationInput): RenderObservation;
declare function hasCompleteNegativeRequestApiProof(observation: RenderObservation, requiredApis: readonly RenderRequestApiKind[]): boolean;
declare function createDisabledCacheProofDecision(input: CreateDisabledCacheProofDecisionInput): DisabledCacheProofDecision;
//#endregion
export { AppRouteCacheProofGraphScope, AppRouteCacheProofGraphScopeInput, BoundaryOutcome, BoundaryOutcomeCompatibility, BuildCacheVariantInput, BuildCacheVariantResult, BuildRenderObservationInput, CACHE_PROOF_MODEL_SCHEMA_VERSION, CacheProofBreakerFallback, CacheProofBreakerFallbackMode, CacheProofFallbackScope, CacheProofModelSchemaVersion, CacheProofOutputScope, CacheProofRejectionCode, CacheProofTraceFieldValue, CacheProofTraceFields, CacheVariant, CacheVariantBudget, CacheVariantDimension, CacheVariantDimensionInput, CacheVariantDimensionPrivacy, CacheVariantDimensionSource, CreateDisabledCacheProofDecisionInput, DEFAULT_CACHE_VARIANT_BUDGET, DisabledCacheProofDecision, RenderCacheability, RenderObservation, RenderObservationCompleteness, RenderRequestApiKind, RenderRequestApiObservation, RenderRequestApiStatus, buildBoundaryOutcomeCompatibility, buildCacheVariant, buildRenderObservation, createAppRouteCacheProofGraphScope, createDisabledCacheProofDecision, hasCompleteNegativeRequestApiProof };
//# sourceMappingURL=cache-proof.d.ts.map