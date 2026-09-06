import { MetadataFileRoute } from "./metadata-routes.js";
import { AppElements } from "./app-elements-wire.js";
import { AppPageParams } from "./app-page-boundary.js";
import { AppRscRenderMode } from "./app-rsc-render-mode.js";
import { AppPageErrorModule, AppPageModule, AppPageRouteWiringRoute } from "./app-page-route-wiring.js";

//#region src/server/app-page-element-builder.d.ts
/**
 * Route shape passed from the generated entry. Extends the wiring route with
 * the page module reference (used to extract the default export for the page
 * element) and the URL pattern (used as the route path in head resolution).
 */
type AppPageBuildRoute<TModule extends AppPageModule = AppPageModule, TErrorModule extends AppPageErrorModule = AppPageErrorModule> = AppPageRouteWiringRoute<TModule, TErrorModule> & {
  page?: TModule | null;
  pattern: string; /** Param names captured by the route's URL pattern, in order. */
  params?: readonly string[] | null;
};
type AppPageInterceptOptions<TModule extends AppPageModule = AppPageModule> = {
  interceptionContext?: string | null;
  interceptLayouts?: readonly (TModule | null | undefined)[] | null;
  interceptPage?: TModule | null;
  interceptParams?: AppPageParams | null;
  interceptSlotKey?: string | null;
};
type AppPagePageRequest<TModule extends AppPageModule = AppPageModule> = {
  /** Interception context from current-route navigation (null for direct visits). */opts?: AppPageInterceptOptions<TModule> | null; /** URL search params from the incoming request (null when unavailable). */
  searchParams?: URLSearchParams | null; /** Whether the incoming request is an RSC (client-side navigation) request. */
  isRscRequest: boolean; /** The incoming HTTP request (available but unused by this module). */
  request: Request; /** Normalized x-vinext-mounted-slots header value. */
  mountedSlotsHeader: string | null; /** Semantic RSC payload mode for this page render. */
  renderMode?: AppRscRenderMode;
};
type BuildPageElementsOptions<TModule extends AppPageModule = AppPageModule, TErrorModule extends AppPageErrorModule = AppPageErrorModule> = {
  route: AppPageBuildRoute<TModule, TErrorModule>;
  params: AppPageParams;
  routePath: string;
  pageRequest: AppPagePageRequest<TModule>; /** Root-level global-error.tsx module. Present when the app defines this file. */
  globalErrorModule?: TErrorModule | null; /** Root-level not-found.tsx module. Present when the app defines this file. */
  rootNotFoundModule?: TModule | null; /** Root-level forbidden.tsx module. Present when the app defines this file. */
  rootForbiddenModule?: TModule | null; /** Root-level unauthorized.tsx module. Present when the app defines this file. */
  rootUnauthorizedModule?: TModule | null; /** File-based metadata routes (favicon, manifest, sitemap, etc.). */
  metadataRoutes: readonly MetadataFileRoute[];
};
/**
 * Build the App Router element tree for a matched route.
 *
 * This is the central element-construction path for the App Router RSC
 * handler. It resolves page head metadata (including parallel route metadata),
 * creates the page React element, and wires it into the nested layout +
 * boundary tree via {@link buildAppPageElements}.
 *
 * The function is extracted from the generated RSC entry template so it can
 * be unit-tested independently of the code-generation machinery.
 *
 * Next.js equivalent: the component tree construction in
 * {@link https://github.com/vercel/next.js/blob/canary/packages/next/src/server/app-render/create-component-tree.tsx|create-component-tree.tsx}
 * and the page head resolution in
 * {@link https://github.com/vercel/next.js/blob/canary/packages/next/src/server/app-render/create-metadata.tsx|create-metadata.tsx}.
 */
declare function buildPageElements<TModule extends AppPageModule = AppPageModule, TErrorModule extends AppPageErrorModule = AppPageErrorModule>(options: BuildPageElementsOptions<TModule, TErrorModule>): Promise<AppElements>;
//#endregion
export { AppPageBuildRoute, type AppPageErrorModule, AppPageInterceptOptions, AppPagePageRequest, type AppPageRouteWiringRoute, BuildPageElementsOptions, buildPageElements };
//# sourceMappingURL=app-page-element-builder.d.ts.map