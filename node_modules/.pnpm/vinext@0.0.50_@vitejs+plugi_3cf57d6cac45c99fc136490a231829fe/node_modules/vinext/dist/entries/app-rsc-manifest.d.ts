import { AppRoute } from "../routing/app-route-graph.js";
import { MetadataFileRoute } from "../server/metadata-routes.js";

//#region src/entries/app-rsc-manifest.d.ts
type AppRscManifestCode = {
  imports: string[];
  routeEntries: string[];
  metaRouteEntries: string[];
  generateStaticParamsEntries: string[];
  rootNotFoundVar: string | null;
  rootForbiddenVar: string | null;
  rootUnauthorizedVar: string | null;
  rootLayoutVars: string[];
  globalErrorVar: string | null;
};
type BuildAppRscManifestCodeOptions = {
  routes: AppRoute[];
  metadataRoutes?: MetadataFileRoute[];
  globalErrorPath?: string | null;
};
declare function buildAppRscManifestCode(options: BuildAppRscManifestCodeOptions): AppRscManifestCode;
//#endregion
export { buildAppRscManifestCode };
//# sourceMappingURL=app-rsc-manifest.d.ts.map