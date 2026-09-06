//#region src/server/app-page-params.ts
function getAppPageSegmentParamName(segment) {
	if (segment.startsWith("[[...") && segment.endsWith("]]") && segment.length > 7) return segment.slice(5, -2);
	if (segment.startsWith("[...") && segment.endsWith("]") && segment.length > 5) return segment.slice(4, -1);
	if (segment.startsWith("[") && segment.endsWith("]") && !segment.includes(".") && segment.length > 2) return segment.slice(1, -1);
	return null;
}
function isEmptyOptionalCatchAll(segment, paramValue) {
	return segment.startsWith("[[...") && Array.isArray(paramValue) && paramValue.length === 0;
}
function resolveAppPageSegmentParams(routeSegments, treePosition, matchedParams) {
	const segmentParams = {};
	const segments = routeSegments ?? [];
	const end = Math.min(Math.max(treePosition, 0), segments.length);
	for (let index = 0; index < end; index++) {
		const segment = segments[index];
		const paramName = getAppPageSegmentParamName(segment);
		if (!paramName) continue;
		const paramValue = matchedParams[paramName];
		if (paramValue === void 0 || isEmptyOptionalCatchAll(segment, paramValue)) continue;
		segmentParams[paramName] = paramValue;
	}
	return segmentParams;
}
//#endregion
export { getAppPageSegmentParamName, resolveAppPageSegmentParams };

//# sourceMappingURL=app-page-params.js.map