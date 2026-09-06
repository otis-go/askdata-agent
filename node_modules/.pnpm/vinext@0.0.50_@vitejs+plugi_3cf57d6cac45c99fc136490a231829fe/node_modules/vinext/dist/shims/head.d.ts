import React from "react";

//#region src/shims/head.d.ts
type HeadProps = {
  children?: React.ReactNode;
};
/**
 * Register ALS-backed state accessors. Called by head-state.ts on import.
 * @internal
 */
declare function _registerHeadStateAccessors(accessors: {
  getSSRHeadChildren: () => React.ReactNode[];
  resetSSRHead: () => void;
}): void;
/** Reset the SSR head collector. Call before render. */
declare function resetSSRHead(): void;
/** Get collected head HTML. Call after render. */
declare function getSSRHeadHTML(): string;
type HeadDOMElement = Pick<HTMLElement, "innerHTML" | "setAttribute" | "textContent">;
declare function reduceHeadChildren(headChildren: React.ReactNode[]): React.ReactElement[];
declare function isSafeAttrName(name: string): boolean;
declare function escapeAttr(s: string): string;
/**
 * Escape content that will be placed inside a raw <script> or <style> tag
 * during SSR. The HTML parser treats `</script>` (or `</style>`) as the end
 * of the block regardless of JavaScript string context, so any occurrence
 * of `</` followed by the tag name must be escaped.
 *
 * We replace `</script` and `</style` (case-insensitive) with `<\/script`
 * and `<\/style` respectively. The `<\/` form is harmless in JS/CSS string
 * context but prevents the HTML parser from seeing a closing tag.
 */
declare function escapeInlineContent(content: string, tag: string): string;
declare function _applyHeadPropsToElement(domEl: HeadDOMElement, props: Record<string, unknown>): void;
declare function Head({
  children
}: HeadProps): null;
//#endregion
export { _applyHeadPropsToElement, _registerHeadStateAccessors, Head as default, escapeAttr, escapeInlineContent, getSSRHeadHTML, isSafeAttrName, reduceHeadChildren, resetSSRHead };
//# sourceMappingURL=head.d.ts.map