import { fnv1a64 } from "../utils/hash.js";
//#region src/server/cache-proof.ts
const CACHE_PROOF_MODEL_SCHEMA_VERSION = 0;
const DEFAULT_CACHE_VARIANT_BUDGET = {
	maxDimensionCount: 8,
	maxDimensionNameLength: 64,
	maxDimensionValueLength: 256,
	maxEncodedLength: 1024,
	maxValuesPerDimension: 8,
	maxVariantsPerRoute: 64
};
const PUBLIC_UNSAFE_DIMENSION_SOURCES = new Set([
	"auth",
	"cookie",
	"draft-mode",
	"header",
	"session"
]);
function buildBreakerFallback(code, fields = {}, mode = "renderFresh", scope = "affectedOutput") {
	return {
		kind: "breakerFallback",
		code,
		mode,
		scope,
		fields
	};
}
function sortedUnique(values) {
	return [...new Set(values)].sort();
}
function normalizeDimensionName(name) {
	return name.trim().toLowerCase();
}
function redactValue(value) {
	return `h:${fnv1a64(value)}`;
}
function sortedUniqueRedacted(values) {
	return sortedUnique(sortedUnique(values).map(redactValue));
}
function encodeParts(parts) {
	return JSON.stringify(parts);
}
function compareDimensions(a, b) {
	return a.source.localeCompare(b.source) || a.name.localeCompare(b.name) || a.privacy.localeCompare(b.privacy);
}
function encodeNullable(value) {
	return value;
}
function assertNever(value) {
	throw new Error(`Unhandled cache proof variant: ${String(value)}`);
}
function encodeOutputScope(output) {
	switch (output.kind) {
		case "app-html": return encodeParts([
			output.kind,
			output.routeId,
			encodeNullable(output.rootBoundaryId),
			encodeNullable(output.renderEpoch)
		]);
		case "app-rsc": return encodeParts([
			output.kind,
			output.routeId,
			encodeNullable(output.rootBoundaryId),
			encodeNullable(output.renderEpoch),
			encodeNullable(output.mountedSlotsFingerprint)
		]);
		case "layout": return encodeParts([
			output.kind,
			output.routeId,
			output.layoutId,
			encodeNullable(output.rootBoundaryId)
		]);
		case "page": return encodeParts([
			output.kind,
			output.routeId,
			output.pageId,
			encodeNullable(output.rootBoundaryId)
		]);
		case "route-handler": return encodeParts([
			output.kind,
			output.routeId,
			output.routeHandlerId
		]);
		case "slot": return encodeParts([
			output.kind,
			output.routeId,
			output.slotId,
			encodeNullable(output.rootBoundaryId)
		]);
		case "template": return encodeParts([
			output.kind,
			output.routeId,
			output.templateId,
			encodeNullable(output.rootBoundaryId)
		]);
		default: return assertNever(output);
	}
}
function validateBudgetNumber(name, value) {
	if (Number.isInteger(value) && value >= 0) return null;
	return buildBreakerFallback("CP_INVALID_VARIANT_BUDGET", { budgetField: name });
}
function validateBudget(budget) {
	return validateBudgetNumber("maxDimensionCount", budget.maxDimensionCount) ?? validateBudgetNumber("maxDimensionNameLength", budget.maxDimensionNameLength) ?? validateBudgetNumber("maxDimensionValueLength", budget.maxDimensionValueLength) ?? validateBudgetNumber("maxEncodedLength", budget.maxEncodedLength) ?? validateBudgetNumber("maxValuesPerDimension", budget.maxValuesPerDimension) ?? validateBudgetNumber("maxVariantsPerRoute", budget.maxVariantsPerRoute);
}
function buildDimension(input, budget) {
	const name = normalizeDimensionName(input.name);
	if (name.length === 0) return buildBreakerFallback("CP_DIMENSION_NAME_MISSING", { source: input.source });
	if (name.length > budget.maxDimensionNameLength) return buildBreakerFallback("CP_DIMENSION_NAME_TOO_LONG", {
		maxLength: budget.maxDimensionNameLength,
		nameHash: redactValue(name),
		source: input.source
	});
	if (input.privacy === "public" && PUBLIC_UNSAFE_DIMENSION_SOURCES.has(input.source)) return buildBreakerFallback("CP_UNSAFE_PUBLIC_DIMENSION", {
		name,
		source: input.source
	}, "privateUncacheable");
	const values = sortedUnique(input.values);
	if (values.length === 0) return buildBreakerFallback("CP_DIMENSION_VALUES_MISSING", {
		name,
		source: input.source
	});
	if (values.length > budget.maxValuesPerDimension) return buildBreakerFallback("CP_DIMENSION_VALUE_COUNT_EXCEEDED", {
		maxValues: budget.maxValuesPerDimension,
		name,
		source: input.source,
		valueCount: values.length
	});
	for (const value of values) if (value.length > budget.maxDimensionValueLength) return buildBreakerFallback("CP_DIMENSION_VALUE_TOO_LONG", {
		maxLength: budget.maxDimensionValueLength,
		name,
		source: input.source,
		valueHash: redactValue(value)
	});
	const valueHashes = values.map(redactValue);
	return {
		encoded: encodeParts([
			input.source,
			input.privacy,
			name,
			valueHashes
		]),
		name,
		privacy: input.privacy,
		source: input.source,
		valueCount: valueHashes.length,
		valueHashes
	};
}
function isCacheProofBreakerFallback(value) {
	return "code" in value;
}
function getDimensionBucket(bySource, source, privacy) {
	const existingByPrivacy = bySource.get(source);
	const byPrivacy = existingByPrivacy ?? /* @__PURE__ */ new Map();
	if (!existingByPrivacy) bySource.set(source, byPrivacy);
	const existingByName = byPrivacy.get(privacy);
	const byName = existingByName ?? /* @__PURE__ */ new Map();
	if (!existingByName) byPrivacy.set(privacy, byName);
	return byName;
}
function mergeDimensionInputs(dimensions) {
	const bySource = /* @__PURE__ */ new Map();
	const orderedDimensions = [];
	for (const dimension of dimensions) {
		const name = normalizeDimensionName(dimension.name);
		const bucket = getDimensionBucket(bySource, dimension.source, dimension.privacy);
		const existing = bucket.get(name);
		if (existing) {
			existing.values.push(...dimension.values);
			continue;
		}
		const accumulator = {
			name,
			privacy: dimension.privacy,
			source: dimension.source,
			values: [...dimension.values]
		};
		bucket.set(name, accumulator);
		orderedDimensions.push(accumulator);
	}
	return orderedDimensions;
}
function createAppRouteCacheProofGraphScope(route) {
	return {
		routeId: route.ids.route,
		pageId: route.ids.page,
		routeHandlerId: route.ids.routeHandler,
		layoutIds: [...route.ids.layouts],
		templateIds: [...route.ids.templates],
		slotIds: sortedUnique(Object.values(route.ids.slots))
	};
}
function buildCacheVariant(input) {
	const budgetFallback = validateBudget(input.budget);
	if (budgetFallback) return {
		kind: "breakerFallback",
		fallback: budgetFallback
	};
	if (input.existingVariantCount >= input.budget.maxVariantsPerRoute) return {
		kind: "breakerFallback",
		fallback: buildBreakerFallback("CP_ROUTE_VARIANT_CEILING_EXCEEDED", {
			existingVariantCount: input.existingVariantCount,
			maxVariantsPerRoute: input.budget.maxVariantsPerRoute,
			routeId: input.output.routeId
		}, "privateUncacheable", "route")
	};
	const dimensionInputs = mergeDimensionInputs(input.dimensions);
	if (dimensionInputs.length > input.budget.maxDimensionCount) return {
		kind: "breakerFallback",
		fallback: buildBreakerFallback("CP_DIMENSION_COUNT_EXCEEDED", {
			dimensionCount: dimensionInputs.length,
			maxDimensionCount: input.budget.maxDimensionCount,
			routeId: input.output.routeId
		})
	};
	const dimensions = [];
	for (const dimensionInput of dimensionInputs) {
		const dimension = buildDimension(dimensionInput, input.budget);
		if (isCacheProofBreakerFallback(dimension)) return {
			kind: "breakerFallback",
			fallback: dimension
		};
		dimensions.push(dimension);
	}
	dimensions.sort(compareDimensions);
	const encoded = [
		`schema:0`,
		encodeOutputScope(input.output),
		...dimensions.map((dimension) => dimension.encoded)
	].join("|");
	if (encoded.length > input.budget.maxEncodedLength) return {
		kind: "breakerFallback",
		fallback: buildBreakerFallback("CP_ENCODED_VARIANT_TOO_LONG", {
			encodedHash: redactValue(encoded),
			encodedLength: encoded.length,
			maxEncodedLength: input.budget.maxEncodedLength,
			routeId: input.output.routeId
		})
	};
	return {
		kind: "variant",
		variant: {
			schemaVersion: 0,
			cacheKey: `cp0:${fnv1a64(encoded)}`,
			output: input.output,
			dimensions,
			encodedLength: encoded.length,
			budget: { ...input.budget }
		}
	};
}
function boundaryOutcomesMatch(expected, candidate) {
	switch (expected.kind) {
		case "error": return candidate.kind === "error" && (expected.digest ?? "") === (candidate.digest ?? "");
		case "forbidden": return candidate.kind === "forbidden";
		case "globalError": return candidate.kind === "globalError" && (expected.digest ?? "") === (candidate.digest ?? "");
		case "notFound": return candidate.kind === "notFound";
		case "redirect": return candidate.kind === "redirect" && expected.status === candidate.status && expected.location === candidate.location;
		case "success": return candidate.kind === "success";
		case "unauthorized": return candidate.kind === "unauthorized";
		case "unknown": return false;
		default: return assertNever(expected);
	}
}
function buildBoundaryOutcomeCompatibility(input) {
	if (input.expected.kind === "unknown" || input.candidate.kind === "unknown") return {
		kind: "incompatible",
		expected: input.expected,
		candidate: input.candidate,
		fallback: buildBreakerFallback("CP_BOUNDARY_OUTCOME_UNKNOWN", {
			candidateKind: input.candidate.kind,
			expectedKind: input.expected.kind
		})
	};
	if (boundaryOutcomesMatch(input.expected, input.candidate)) return {
		kind: "compatible",
		outcome: input.candidate,
		reason: "CP_BOUNDARY_OUTCOME_MATCH"
	};
	return {
		kind: "incompatible",
		expected: input.expected,
		candidate: input.candidate,
		fallback: buildBreakerFallback("CP_BOUNDARY_OUTCOME_MISMATCH", {
			candidateKind: input.candidate.kind,
			expectedKind: input.expected.kind
		})
	};
}
function requestApiStatusRank(status) {
	switch (status) {
		case "notObserved": return 0;
		case "unknown": return 1;
		case "observed": return 2;
		default: return assertNever(status);
	}
}
function normalizeRequestApiObservations(observations) {
	const byKind = /* @__PURE__ */ new Map();
	for (const observation of observations) {
		const current = byKind.get(observation.kind);
		if (current === void 0 || requestApiStatusRank(observation.status) > requestApiStatusRank(current)) byKind.set(observation.kind, observation.status);
	}
	return [...byKind.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([kind, status]) => ({
		kind,
		status
	}));
}
function buildRenderObservation(input) {
	return {
		schemaVersion: 0,
		output: input.output,
		completeness: input.completeness,
		boundaryOutcome: input.boundaryOutcome,
		requestApis: normalizeRequestApiObservations(input.requestApis),
		dynamicFetches: sortedUniqueRedacted(input.dynamicFetches),
		cacheTags: sortedUnique(input.cacheTags),
		pathTags: sortedUnique(input.pathTags),
		cacheability: input.cacheability
	};
}
function hasCompleteNegativeRequestApiProof(observation, requiredApis) {
	if (observation.completeness !== "complete") return false;
	const statuses = /* @__PURE__ */ new Map();
	for (const requestApi of observation.requestApis) statuses.set(requestApi.kind, requestApi.status);
	for (const api of requiredApis) if (statuses.get(api) !== "notObserved") return false;
	return true;
}
function createDisabledCacheProofDecision(input) {
	return {
		kind: "disabled",
		canReuse: false,
		variant: input.variant,
		observation: input.observation,
		fallback: buildBreakerFallback("CP_MODEL_DISABLED")
	};
}
//#endregion
export { CACHE_PROOF_MODEL_SCHEMA_VERSION, DEFAULT_CACHE_VARIANT_BUDGET, buildBoundaryOutcomeCompatibility, buildCacheVariant, buildRenderObservation, createAppRouteCacheProofGraphScope, createDisabledCacheProofDecision, hasCompleteNegativeRequestApiProof };

//# sourceMappingURL=cache-proof.js.map