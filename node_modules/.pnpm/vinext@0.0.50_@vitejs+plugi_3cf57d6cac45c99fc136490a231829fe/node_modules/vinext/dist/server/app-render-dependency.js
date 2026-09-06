import { Fragment, jsx, jsxs } from "react/jsx-runtime";
//#region src/server/app-render-dependency.tsx
function createAppRenderDependency() {
	let released = false;
	let resolve;
	return {
		promise: new Promise((promiseResolve) => {
			resolve = promiseResolve;
		}),
		release() {
			if (released) return;
			released = true;
			resolve();
		}
	};
}
function renderAfterAppDependencies(children, dependencies) {
	if (dependencies.length === 0) return children;
	async function AwaitAppRenderDependencies() {
		await Promise.all(dependencies.map((dependency) => dependency.promise));
		return children;
	}
	return /* @__PURE__ */ jsx(AwaitAppRenderDependencies, {});
}
function renderWithAppDependencyBarrier(children, dependency) {
	function ReleaseAppRenderDependency() {
		dependency.release();
		return null;
	}
	return /* @__PURE__ */ jsxs(Fragment, { children: [children, /* @__PURE__ */ jsx(ReleaseAppRenderDependency, {})] });
}
//#endregion
export { createAppRenderDependency, renderAfterAppDependencies, renderWithAppDependencyBarrier };

//# sourceMappingURL=app-render-dependency.js.map