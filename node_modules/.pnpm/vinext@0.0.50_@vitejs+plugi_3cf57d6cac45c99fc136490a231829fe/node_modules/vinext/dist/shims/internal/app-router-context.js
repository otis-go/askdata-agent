import { createContext } from "react";
//#region src/shims/internal/app-router-context.ts
/**
* Shim for next/dist/shared/lib/app-router-context.shared-runtime
*
* Used by: @clerk/nextjs, next-intl, next-nprogress-bar, nextjs-toploader,
* next-view-transitions. Mostly type-only imports in published .d.ts files.
*
* We export the types and minimal context objects so these libraries resolve.
*/
const AppRouterContext = createContext(null);
const GlobalLayoutRouterContext = createContext(null);
const LayoutRouterContext = createContext(null);
const MissingSlotContext = createContext(/* @__PURE__ */ new Set());
const TemplateContext = createContext(null);
//#endregion
export { AppRouterContext, GlobalLayoutRouterContext, LayoutRouterContext, MissingSlotContext, TemplateContext };

//# sourceMappingURL=app-router-context.js.map