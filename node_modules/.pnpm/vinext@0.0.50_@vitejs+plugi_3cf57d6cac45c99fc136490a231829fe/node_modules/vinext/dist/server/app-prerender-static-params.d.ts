import { RootParams } from "../shims/root-params.js";

//#region src/server/app-prerender-static-params.d.ts
type GenerateStaticParamsFunction = (input: {
  params: RootParams;
}) => unknown;
type CallAppPrerenderStaticParamsOptions = {
  fn: GenerateStaticParamsFunction;
  params: RootParams;
  pattern: string;
  rootParamNamesByPattern: Record<string, readonly string[] | undefined>;
};
declare function callAppPrerenderStaticParams(options: CallAppPrerenderStaticParamsOptions): Promise<unknown>;
//#endregion
export { callAppPrerenderStaticParams };
//# sourceMappingURL=app-prerender-static-params.d.ts.map