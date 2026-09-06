import * as _$react from "react";

//#region src/shims/internal/app-router-context.d.ts
type NavigateOptions = {
  scroll?: boolean;
};
type PrefetchOptions = {
  kind?: unknown;
  onInvalidate?: () => void;
};
type AppRouterInstance = {
  bfcacheId: string;
  back(): void;
  forward(): void;
  refresh(): void;
  push(href: string, options?: NavigateOptions): void;
  replace(href: string, options?: NavigateOptions): void;
  prefetch(href: string, options?: PrefetchOptions): void;
};
declare const AppRouterContext: _$react.Context<AppRouterInstance | null>;
declare const GlobalLayoutRouterContext: _$react.Context<unknown>;
declare const LayoutRouterContext: _$react.Context<unknown>;
declare const MissingSlotContext: _$react.Context<Set<string>>;
declare const TemplateContext: _$react.Context<unknown>;
//#endregion
export { AppRouterContext, AppRouterInstance, GlobalLayoutRouterContext, LayoutRouterContext, MissingSlotContext, NavigateOptions, PrefetchOptions, TemplateContext };
//# sourceMappingURL=app-router-context.d.ts.map