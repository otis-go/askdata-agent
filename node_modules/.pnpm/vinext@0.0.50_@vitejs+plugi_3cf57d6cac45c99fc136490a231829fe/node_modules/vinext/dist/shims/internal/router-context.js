import { createContext } from "react";
//#region src/shims/internal/router-context.ts
/**
* Shim for next/dist/shared/lib/router-context.shared-runtime
*
* Used by: some testing utilities and older libraries.
* Provides the Pages Router context.
*/
const RouterContext = createContext(null);
//#endregion
export { RouterContext };

//# sourceMappingURL=router-context.js.map