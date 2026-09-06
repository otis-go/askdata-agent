import { ReactNode } from "react";

//#region src/server/app-render-dependency.d.ts
type AppRenderDependency = {
  promise: Promise<void>;
  release: () => void;
};
declare function createAppRenderDependency(): AppRenderDependency;
declare function renderAfterAppDependencies(children: ReactNode, dependencies: readonly AppRenderDependency[]): ReactNode;
declare function renderWithAppDependencyBarrier(children: ReactNode, dependency: AppRenderDependency): ReactNode;
//#endregion
export { AppRenderDependency, createAppRenderDependency, renderAfterAppDependencies, renderWithAppDependencyBarrier };
//# sourceMappingURL=app-render-dependency.d.ts.map