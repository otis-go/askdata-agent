import "react";
import { jsx, jsxs } from "react/jsx-runtime";
//#region src/shims/document.tsx
function Html({ children, lang, ...props }) {
	return /* @__PURE__ */ jsx("html", {
		lang,
		...props,
		children
	});
}
/**
* Document Head - renders <head> with children.
* The dev server injects meta tags, styles, etc.
*/
function Head({ children }) {
	return /* @__PURE__ */ jsxs("head", { children: [
		/* @__PURE__ */ jsx("meta", { charSet: "utf-8" }),
		/* @__PURE__ */ jsx("meta", {
			name: "viewport",
			content: "width=device-width, initial-scale=1"
		}),
		children
	] });
}
/**
* Main - renders the page content container.
*/
function Main() {
	return /* @__PURE__ */ jsx("div", {
		id: "__next",
		dangerouslySetInnerHTML: { __html: "__NEXT_MAIN__" }
	});
}
/**
* NextScript - renders a placeholder that the dev-server replaces with
* actual hydration scripts (__NEXT_DATA__ + entry module).
* Uses dangerouslySetInnerHTML so the HTML comment survives renderToString.
*/
function NextScript() {
	return /* @__PURE__ */ jsx("span", { dangerouslySetInnerHTML: { __html: "<!-- __NEXT_SCRIPTS__ -->" } });
}
/**
* Default Document component - used when no custom _document.tsx exists.
*/
function Document() {
	return /* @__PURE__ */ jsxs(Html, { children: [/* @__PURE__ */ jsx(Head, {}), /* @__PURE__ */ jsxs("body", { children: [/* @__PURE__ */ jsx(Main, {}), /* @__PURE__ */ jsx(NextScript, {})] })] });
}
//#endregion
export { Head, Html, Main, NextScript, Document as default };

//# sourceMappingURL=document.js.map