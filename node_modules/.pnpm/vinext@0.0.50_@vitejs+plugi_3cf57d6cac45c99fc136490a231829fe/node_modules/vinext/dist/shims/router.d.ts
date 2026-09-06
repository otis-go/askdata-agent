import { VinextNextData } from "../client/vinext-next-data.js";
import { UrlQuery } from "../utils/query.js";
import { ComponentType, ReactElement } from "react";

//#region src/shims/router.d.ts
type BeforePopStateCallback = (state: {
  url: string;
  as: string;
  options: {
    shallow: boolean;
  };
}) => boolean;
type NextRouter = {
  /** Current pathname */pathname: string; /** Current route pattern (e.g., "/posts/[id]") */
  route: string; /** Query parameters */
  query: Record<string, string | string[]>; /** Full URL including query string */
  asPath: string; /** Base path */
  basePath: string; /** Current locale */
  locale?: string; /** Available locales */
  locales?: string[]; /** Default locale */
  defaultLocale?: string; /** Configured domain locales */
  domainLocales?: VinextNextData["domainLocales"]; /** Whether the router is ready */
  isReady: boolean; /** Whether this is a preview */
  isPreview: boolean; /** Whether this is a fallback page */
  isFallback: boolean; /** Navigate to a new URL */
  push(url: string | UrlObject, as?: string, options?: TransitionOptions): Promise<boolean>; /** Replace current URL */
  replace(url: string | UrlObject, as?: string, options?: TransitionOptions): Promise<boolean>; /** Go back */
  back(): void; /** Reload the page */
  reload(): void; /** Prefetch a page (injects <link rel="prefetch">) */
  prefetch(url: string): Promise<void>; /** Register a callback to run before popstate navigation */
  beforePopState(cb: BeforePopStateCallback): void; /** Listen for route changes */
  events: RouterEvents;
};
type UrlObject = {
  pathname?: string;
  query?: UrlQuery;
};
type TransitionOptions = {
  shallow?: boolean;
  scroll?: boolean;
  locale?: string;
};
type RouterEvents = {
  on(event: string, handler: (...args: unknown[]) => void): void;
  off(event: string, handler: (...args: unknown[]) => void): void;
  emit(event: string, ...args: unknown[]): void;
};
/**
 * Apply locale prefix to a URL for client-side navigation.
 * Same logic as Link's applyLocaleToHref but reads from window globals.
 */
declare function applyNavigationLocale(url: string, locale?: string): string;
/** Check if a URL is external (any URL scheme per RFC 3986, or protocol-relative) */
declare function isExternalUrl(url: string): boolean;
/** Check if a href is only a hash change relative to the current URL */
declare function isHashOnlyChange(href: string): boolean;
/**
 * SSR context - set by the dev server before rendering each page.
 */
type SSRContext = {
  pathname: string;
  query: Record<string, string | string[]>;
  asPath: string;
  locale?: string;
  locales?: string[];
  defaultLocale?: string;
  domainLocales?: VinextNextData["domainLocales"];
};
/**
 * Register ALS-backed state accessors. Called by router-state.ts on import.
 * @internal
 */
declare function _registerRouterStateAccessors(accessors: {
  getSSRContext: () => SSRContext | null;
  setSSRContext: (ctx: SSRContext | null) => void;
}): void;
declare function setSSRContext(ctx: SSRContext | null): void;
/**
 * useRouter hook - Pages Router compatible.
 */
declare function useRouter(): NextRouter;
/**
 * Wrap a React element in a RouterContext.Provider so that
 * next/compat/router's useRouter() returns the real Pages Router value.
 *
 * This is a plain function, NOT a React component — it builds the router
 * value object directly from the current SSR context (server) or
 * window.location + Router singleton (client), avoiding duplicate state
 * that a hook-based component would create.
 */
declare function wrapWithRouterContext(element: ReactElement): ReactElement;
/**
 * Props injected by `withRouter` into the wrapped component.
 *
 * Ported from Next.js: packages/next/src/client/with-router.tsx
 * https://github.com/vercel/next.js/blob/canary/packages/next/src/client/with-router.tsx
 */
type WithRouterProps = {
  router: NextRouter;
};
/**
 * Pick<P, Exclude<keyof P, keyof WithRouterProps>> — the props of the
 * composed component minus the `router` prop that `withRouter` injects.
 *
 * Ported from Next.js: packages/next/src/client/with-router.tsx
 */
type ExcludeRouterProps<P> = Pick<P, Exclude<keyof P, keyof WithRouterProps>>;
/**
 * Higher-order component that injects the Pages Router `router` instance as
 * a `router` prop into a wrapped component. Primarily used by class
 * components (which cannot call hooks) to access the router. The wrapped
 * component receives the same props as the original, minus `router`, which
 * is filled in by the HOC.
 *
 * Ported from Next.js: packages/next/src/client/with-router.tsx
 * https://github.com/vercel/next.js/blob/canary/packages/next/src/client/with-router.tsx
 *
 * Differences from Next.js:
 * - We type the composed component as `ComponentType<P>` instead of
 *   `NextComponentType<C, any, P>` because vinext does not expose
 *   `NextComponentType` from this shim. The runtime shape (and the props
 *   the wrapper forwards) is identical.
 * - We forward `getInitialProps` and `origGetInitialProps` from the
 *   composed component so `_app` parity holds for class components that
 *   define `getInitialProps`.
 */
declare function withRouter<P extends WithRouterProps>(ComposedComponent: ComponentType<P>): ComponentType<ExcludeRouterProps<P>>;
declare const Router: {
  push: (url: string | UrlObject, as?: string, options?: TransitionOptions) => Promise<boolean>;
  replace: (url: string | UrlObject, as?: string, options?: TransitionOptions) => Promise<boolean>;
  back: () => void;
  reload: () => void;
  prefetch: (url: string) => Promise<void>;
  beforePopState: (cb: BeforePopStateCallback) => void;
  events: RouterEvents;
};
//#endregion
export { ExcludeRouterProps, NextRouter, WithRouterProps, _registerRouterStateAccessors, applyNavigationLocale, Router as default, isExternalUrl, isHashOnlyChange, setSSRContext, useRouter, withRouter, wrapWithRouterContext };
//# sourceMappingURL=router.d.ts.map