import { Route } from "../routing/pages-router.js";
import { ModuleImporter } from "./instrumentation.js";
import { IncomingMessage, ServerResponse } from "node:http";

//#region src/server/api-handler.d.ts
/**
 * Handle an API route request.
 * Returns true if the request was handled, false if no API route matched.
 */
declare function handleApiRoute(runner: ModuleImporter, req: IncomingMessage, res: ServerResponse, url: string, apiRoutes: Route[]): Promise<boolean>;
//#endregion
export { handleApiRoute };
//# sourceMappingURL=api-handler.d.ts.map