"use client";
import { AppElementsWire, UNMATCHED_SLOT } from "../server/app-elements-wire.js";
import "../server/app-elements.js";
import { notFound } from "./navigation.js";
import * as React$1 from "react";
import { jsx } from "react/jsx-runtime";
//#region src/shims/slot.tsx
const EMPTY_ELEMENTS = Object.freeze({});
const warnedMissingEntryIds = /* @__PURE__ */ new Set();
/**
* Holds resolved AppElements (not a Promise). React 19's use(Promise) during
* hydration triggers "async Client Component" for native Promises that lack
* React's internal .status property. Storing resolved values sidesteps this.
*/
const ElementsContext = React$1.createContext(EMPTY_ELEMENTS);
const ChildrenContext = React$1.createContext(null);
const ParallelSlotsContext = React$1.createContext(null);
function mergeElements(prev, next, options = {}) {
	const clearAbsentSlots = typeof options === "boolean" ? options : options.clearAbsentSlots ?? false;
	const preserveAbsentSlots = typeof options === "boolean" ? !options : options.preserveAbsentSlots ?? true;
	const preserveElementIds = typeof options === "boolean" ? [] : options.preserveElementIds ?? [];
	const merged = { ...next };
	for (const id of preserveElementIds) {
		if (Object.hasOwn(merged, id)) continue;
		if (Object.hasOwn(prev, id)) {
			const value = prev[id];
			if (value !== void 0) merged[id] = value;
		}
	}
	const slotKeys = new Set([...Object.keys(prev), ...Object.keys(next)].filter((key) => AppElementsWire.isSlotId(key)));
	for (const key of slotKeys) if (next[key] === UNMATCHED_SLOT && Object.hasOwn(prev, key)) merged[key] = prev[key];
	if (clearAbsentSlots) {
		for (const key of slotKeys) if (!Object.hasOwn(next, key)) delete merged[key];
	} else if (preserveAbsentSlots) {
		for (const key of slotKeys) if (!Object.hasOwn(merged, key) && Object.hasOwn(prev, key)) {
			const value = prev[key];
			if (value !== void 0) merged[key] = value;
		}
	}
	return merged;
}
function Slot({ id, children, parallelSlots }) {
	const elements = React$1.useContext(ElementsContext);
	if (!Object.hasOwn(elements, id)) {
		if (process.env.NODE_ENV !== "production" && !AppElementsWire.isSlotId(id)) {
			if (!warnedMissingEntryIds.has(id)) {
				warnedMissingEntryIds.add(id);
				console.warn("[vinext] Missing App Router element entry during render: " + id);
			}
		}
		return null;
	}
	const element = elements[id];
	if (element === UNMATCHED_SLOT) notFound();
	return /* @__PURE__ */ jsx(ParallelSlotsContext.Provider, {
		value: parallelSlots ?? null,
		children: /* @__PURE__ */ jsx(ChildrenContext.Provider, {
			value: children ?? null,
			children: element
		})
	});
}
function Children() {
	return React$1.useContext(ChildrenContext);
}
function ParallelSlot({ name }) {
	return React$1.useContext(ParallelSlotsContext)?.[name] ?? null;
}
//#endregion
export { Children, ChildrenContext, ElementsContext, ParallelSlot, ParallelSlotsContext, Slot, UNMATCHED_SLOT, mergeElements };

//# sourceMappingURL=slot.js.map