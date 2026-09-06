import { AppElementValue, AppElements, UNMATCHED_SLOT } from "../server/app-elements-wire.js";
import * as React$1 from "react";
import * as _$react_jsx_runtime0 from "react/jsx-runtime";

//#region src/shims/slot.d.ts
/**
 * Holds resolved AppElements (not a Promise). React 19's use(Promise) during
 * hydration triggers "async Client Component" for native Promises that lack
 * React's internal .status property. Storing resolved values sidesteps this.
 */
declare const ElementsContext: React$1.Context<Readonly<Record<string, AppElementValue>>>;
declare const ChildrenContext: React$1.Context<React$1.ReactNode>;
declare const ParallelSlotsContext: React$1.Context<Readonly<Record<string, React$1.ReactNode>> | null>;
type MergeElementsOptions = {
  clearAbsentSlots?: boolean;
  preserveAbsentSlots?: boolean;
  preserveElementIds?: readonly string[];
};
declare function mergeElements(prev: AppElements, next: AppElements, options?: MergeElementsOptions | boolean): AppElements;
declare function Slot({
  id,
  children,
  parallelSlots
}: {
  id: string;
  children?: React$1.ReactNode;
  parallelSlots?: Readonly<Record<string, React$1.ReactNode>>;
}): _$react_jsx_runtime0.JSX.Element | null;
declare function Children(): React$1.ReactNode;
declare function ParallelSlot({
  name
}: {
  name: string;
}): string | number | bigint | boolean | React$1.ReactElement<unknown, string | React$1.JSXElementConstructor<any>> | Iterable<React$1.ReactNode> | Promise<string | number | bigint | boolean | React$1.ReactPortal | React$1.ReactElement<unknown, string | React$1.JSXElementConstructor<any>> | Iterable<React$1.ReactNode> | null | undefined> | null;
//#endregion
export { Children, ChildrenContext, ElementsContext, ParallelSlot, ParallelSlotsContext, Slot, UNMATCHED_SLOT, mergeElements };
//# sourceMappingURL=slot.d.ts.map