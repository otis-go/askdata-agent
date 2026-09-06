import { VinextLinkPrefetchRoute } from "../client/vinext-next-data.js";
import { UrlQuery } from "../utils/query.js";
import React, { AnchorHTMLAttributes } from "react";

//#region src/shims/link.d.ts
type NavigateEvent = {
  url: URL; /** Call to prevent the Link's default navigation (e.g. for View Transitions). */
  preventDefault(): void; /** Whether preventDefault() has been called. */
  defaultPrevented: boolean;
};
type LinkProps = {
  href: string | {
    pathname?: string;
    query?: UrlQuery;
  }; /** URL displayed in the browser (when href is a route pattern like /user/[id]) */
  as?: string; /** Replace the current history entry instead of pushing */
  replace?: boolean; /** Prefetch the page in the background (App Router default: auto, Pages Router default: true) */
  prefetch?: boolean | "auto" | null; /** Whether to pass the href to the child element */
  passHref?: boolean; /** Scroll to top on navigation (default: true) */
  scroll?: boolean; /** Locale for i18n (used for locale-prefixed URLs) */
  locale?: string | false; /** Called before navigation happens (Next.js 16). Return value is ignored. */
  onNavigate?: (event: NavigateEvent) => void;
  children?: React.ReactNode;
} & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">;
type LinkPrefetchMode = "disabled" | "auto" | "full";
declare global {
  interface Window {
    __VINEXT_LINK_PREFETCH_ROUTES__?: VinextLinkPrefetchRoute[];
  }
}
type LinkStatusContextValue = {
  pending: boolean;
};
/**
 * useLinkStatus returns the pending state of the enclosing <Link>.
 * In Next.js, this is used to show loading indicators while a
 * prefetch-triggered navigation is in progress.
 */
declare function useLinkStatus(): LinkStatusContextValue;
declare function resolveLinkPrefetchMode(prefetchProp: LinkProps["prefetch"], isDangerous: boolean): LinkPrefetchMode;
declare function canAutoPrefetchFullAppRoute(href: string): boolean;
declare const Link: React.ForwardRefExoticComponent<{
  href: string | {
    pathname?: string;
    query?: UrlQuery;
  }; /** URL displayed in the browser (when href is a route pattern like /user/[id]) */
  as?: string; /** Replace the current history entry instead of pushing */
  replace?: boolean; /** Prefetch the page in the background (App Router default: auto, Pages Router default: true) */
  prefetch?: boolean | "auto" | null; /** Whether to pass the href to the child element */
  passHref?: boolean; /** Scroll to top on navigation (default: true) */
  scroll?: boolean; /** Locale for i18n (used for locale-prefixed URLs) */
  locale?: string | false; /** Called before navigation happens (Next.js 16). Return value is ignored. */
  onNavigate?: (event: NavigateEvent) => void;
  children?: React.ReactNode;
} & Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & React.RefAttributes<HTMLAnchorElement>>;
//#endregion
export { canAutoPrefetchFullAppRoute, Link as default, resolveLinkPrefetchMode, useLinkStatus };
//# sourceMappingURL=link.d.ts.map