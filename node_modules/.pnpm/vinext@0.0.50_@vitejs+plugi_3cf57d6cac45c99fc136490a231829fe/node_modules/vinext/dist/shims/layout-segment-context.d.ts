import { SegmentMap } from "./navigation.js";
import * as _$react from "react";
import { ReactNode } from "react";

//#region src/shims/layout-segment-context.d.ts
/**
 * Wraps children with the layout segment context.
 *
 * Each layout in the App Router tree wraps its children with this provider,
 * passing a map of parallel route key to segment path. The "children" key is
 * always present (the default parallel route). Named parallel slots at this
 * layout level add their own keys.
 *
 * Components inside the provider call useSelectedLayoutSegments(parallelRoutesKey)
 * to read the segments for a specific parallel route.
 */
declare function LayoutSegmentProvider({
  segmentMap,
  children
}: {
  segmentMap: SegmentMap;
  children: ReactNode;
}): string | number | bigint | boolean | _$react.ReactElement<unknown, string | _$react.JSXElementConstructor<any>> | Iterable<ReactNode> | Promise<string | number | bigint | boolean | _$react.ReactPortal | _$react.ReactElement<unknown, string | _$react.JSXElementConstructor<any>> | Iterable<ReactNode> | null | undefined> | _$react.FunctionComponentElement<_$react.ProviderProps<SegmentMap>> | null | undefined;
//#endregion
export { LayoutSegmentProvider };
//# sourceMappingURL=layout-segment-context.d.ts.map