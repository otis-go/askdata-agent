import { MetadataFileRoute } from "./metadata-routes.js";

//#region src/server/metadata-route-response.d.ts
type AppPageParams = Record<string, string | string[]>;
type MakeThenableParams = (params: AppPageParams) => unknown;
type MetadataRuntimeRoute = MetadataFileRoute & {
  fileDataBase64?: string;
};
type MetadataRouteRequestOptions = {
  metadataRoutes: readonly MetadataRuntimeRoute[];
  cleanPathname: string;
  makeThenableParams: MakeThenableParams;
};
declare function handleMetadataRouteRequest(options: MetadataRouteRequestOptions): Promise<Response | null>;
//#endregion
export { handleMetadataRouteRequest };
//# sourceMappingURL=metadata-route-response.d.ts.map