import React from "react";
import * as _$react_jsx_runtime0 from "react/jsx-runtime";

//#region src/shims/document.d.ts
declare function Html({
  children,
  lang,
  ...props
}: React.HTMLAttributes<HTMLHtmlElement> & {
  children?: React.ReactNode;
}): _$react_jsx_runtime0.JSX.Element;
/**
 * Document Head - renders <head> with children.
 * The dev server injects meta tags, styles, etc.
 */
declare function Head({
  children
}: {
  children?: React.ReactNode;
}): _$react_jsx_runtime0.JSX.Element;
/**
 * Main - renders the page content container.
 */
declare function Main(): _$react_jsx_runtime0.JSX.Element;
/**
 * NextScript - renders a placeholder that the dev-server replaces with
 * actual hydration scripts (__NEXT_DATA__ + entry module).
 * Uses dangerouslySetInnerHTML so the HTML comment survives renderToString.
 */
declare function NextScript(): _$react_jsx_runtime0.JSX.Element;
/**
 * Default Document component - used when no custom _document.tsx exists.
 */
declare function Document(): _$react_jsx_runtime0.JSX.Element;
//#endregion
export { Head, Html, Main, NextScript, Document as default };
//# sourceMappingURL=document.d.ts.map