import { Route } from "../routing/pages-router.js";
import { PagesReqResRequest, PagesReqResResponse, PagesRequestQuery } from "./pages-node-compat.js";

//#region src/server/pages-api-route.d.ts
type PagesApiRouteModule = {
  default?: (req: PagesReqResRequest, res: PagesReqResResponse) => void | Promise<void>;
};
type PagesApiRouteMatch = {
  params: PagesRequestQuery;
  route: Pick<Route, "pattern"> & {
    module: PagesApiRouteModule;
  };
};
type HandlePagesApiRouteOptions = {
  match: PagesApiRouteMatch | null;
  reportRequestError?: (error: Error, routePattern: string) => void | Promise<void>;
  request: Request;
  url: string;
};
declare function handlePagesApiRoute(options: HandlePagesApiRouteOptions): Promise<Response>;
//#endregion
export { PagesApiRouteMatch, handlePagesApiRoute };
//# sourceMappingURL=pages-api-route.d.ts.map