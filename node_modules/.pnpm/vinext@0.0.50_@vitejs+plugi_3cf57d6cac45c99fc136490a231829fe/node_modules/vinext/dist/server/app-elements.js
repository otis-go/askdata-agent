import { normalizeMountedSlotsHeader } from "./app-mounted-slots-header.js";
import { APP_ARTIFACT_COMPATIBILITY_KEY, APP_INTERCEPTION_CONTEXT_KEY, APP_LAYOUT_FLAGS_KEY, APP_LAYOUT_IDS_KEY, APP_ROOT_LAYOUT_KEY, APP_ROUTE_KEY, APP_UNMATCHED_SLOT_WIRE_VALUE, AppElementsWire, UNMATCHED_SLOT, buildOutgoingAppPayload, isAppElementsRecord, normalizeAppElements, readAppElementsMetadata, withLayoutFlags } from "./app-elements-wire.js";
//#region src/server/app-elements.ts
function getMountedSlotIds(elements) {
	return Object.keys(elements).filter((key) => {
		const value = elements[key];
		return AppElementsWire.isSlotId(key) && value !== null && value !== void 0 && value !== UNMATCHED_SLOT;
	}).sort();
}
function getMountedSlotIdsHeader(elements) {
	return normalizeMountedSlotsHeader(getMountedSlotIds(elements).join(" "));
}
function resolveVisitedResponseInterceptionContext(requestInterceptionContext, payloadInterceptionContext) {
	return payloadInterceptionContext ?? requestInterceptionContext;
}
//#endregion
export { APP_ARTIFACT_COMPATIBILITY_KEY, APP_INTERCEPTION_CONTEXT_KEY, APP_LAYOUT_FLAGS_KEY, APP_LAYOUT_IDS_KEY, APP_ROOT_LAYOUT_KEY, APP_ROUTE_KEY, APP_UNMATCHED_SLOT_WIRE_VALUE, AppElementsWire, UNMATCHED_SLOT, buildOutgoingAppPayload, getMountedSlotIds, getMountedSlotIdsHeader, isAppElementsRecord, normalizeAppElements, readAppElementsMetadata, resolveVisitedResponseInterceptionContext, withLayoutFlags };

//# sourceMappingURL=app-elements.js.map