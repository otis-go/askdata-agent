import React from "react";
//#region src/shims/error.tsx
/**
* next/error shim
*
* Provides the default Next.js error page component.
* Used by apps that import `import Error from 'next/error'` for
* custom error handling in getServerSideProps or API routes.
*/
function ErrorComponent({ statusCode, title }) {
	const displayTitle = title ?? (statusCode === 404 ? "This page could not be found" : "Internal Server Error");
	return React.createElement("div", { style: {
		fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif",
		height: "100vh",
		textAlign: "center",
		display: "flex",
		flexDirection: "column",
		alignItems: "center",
		justifyContent: "center"
	} }, React.createElement("div", null, React.createElement("h1", { style: {
		display: "inline-block",
		margin: "0 20px 0 0",
		padding: "0 23px 0 0",
		fontSize: 24,
		fontWeight: 500,
		verticalAlign: "top",
		lineHeight: "49px",
		borderRight: "1px solid rgba(0, 0, 0, .3)"
	} }, statusCode), React.createElement("div", { style: { display: "inline-block" } }, React.createElement("h2", { style: {
		fontSize: 14,
		fontWeight: 400,
		lineHeight: "49px",
		margin: 0
	} }, displayTitle + "."))));
}
//#endregion
export { ErrorComponent as default };

//# sourceMappingURL=error.js.map