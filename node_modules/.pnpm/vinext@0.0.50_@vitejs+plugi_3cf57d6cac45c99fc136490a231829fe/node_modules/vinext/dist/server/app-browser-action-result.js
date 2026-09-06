//#region src/server/app-browser-action-result.ts
/**
* Structural discriminator: matches on `"returnValue"` or `"root"` keys.
* This is safe because {@link AppWireElements} keys are prefixed (`route:`,
* `slot:`, `__route`, etc.) and will never collide with these property names.
* If the wire format ever adds a `"root"` key, this guard must be updated.
*/
function isServerActionResult(value) {
	return !!value && typeof value === "object" && ("returnValue" in value || "root" in value);
}
function shouldClearClientNavigationCachesForServerActionResult(result) {
	if (!isServerActionResult(result)) return true;
	return result.root !== void 0;
}
//#endregion
export { isServerActionResult, shouldClearClientNavigationCachesForServerActionResult };

//# sourceMappingURL=app-browser-action-result.js.map