//#region src/shims/root-params.d.ts
type RootParams = Record<string, string | string[] | undefined>;
type RootParamsState = {
  rootParams: RootParams | null;
};
declare function pickRootParams(params: RootParams, rootParamNames: readonly string[] | null | undefined): RootParams;
declare function setRootParams(params: RootParams | null): void;
declare function getRootParam(name: string): Promise<string | string[] | undefined>;
//#endregion
export { RootParams, RootParamsState, getRootParam, pickRootParams, setRootParams };
//# sourceMappingURL=root-params.d.ts.map