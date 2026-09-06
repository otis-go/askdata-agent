import { MetadataFileRoute } from "./metadata-routes.js";
import { Metadata } from "../shims/metadata.js";

//#region src/server/file-based-metadata.d.ts
type AppPageParams = Record<string, string | string[]>;
type FileBasedMetadataSource = {
  routeSegments: readonly string[];
  metadata: Metadata | null;
};
type FileBasedMetadataOptions = {
  routeSegments?: readonly string[] | null;
  metadataSources?: readonly FileBasedMetadataSource[] | null;
};
declare function applyFileBasedMetadata(metadata: Metadata | null, routePath: string, params: AppPageParams, metadataRoutes: readonly MetadataFileRoute[] | null | undefined, options?: FileBasedMetadataOptions): Promise<Metadata | null>;
//#endregion
export { applyFileBasedMetadata };
//# sourceMappingURL=file-based-metadata.d.ts.map