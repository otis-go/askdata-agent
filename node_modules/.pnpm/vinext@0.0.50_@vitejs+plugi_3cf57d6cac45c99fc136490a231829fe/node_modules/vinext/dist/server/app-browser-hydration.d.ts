import { ReactFormState, hydrateRoot } from "react-dom/client";

//#region src/server/app-browser-hydration.d.ts
type HydrateRootOptions = NonNullable<Parameters<typeof hydrateRoot>[2]>;
type HydrateRootCaughtErrorHandler = NonNullable<HydrateRootOptions["onCaughtError"]>;
type HydrateRootUncaughtErrorHandler = NonNullable<HydrateRootOptions["onUncaughtError"]>;
declare const RSC_FORM_STATE_GLOBAL = "__VINEXT_RSC_FORM_STATE__";
type FormStateGlobal = {
  [RSC_FORM_STATE_GLOBAL]?: ReactFormState;
};
declare function consumeInitialFormState(global: FormStateGlobal): ReactFormState | null;
declare function createVinextHydrateRootOptions(options: {
  formState: ReactFormState | null;
  onCaughtError?: HydrateRootCaughtErrorHandler;
  onUncaughtError: HydrateRootUncaughtErrorHandler;
}): HydrateRootOptions;
//#endregion
export { RSC_FORM_STATE_GLOBAL, consumeInitialFormState, createVinextHydrateRootOptions };
//# sourceMappingURL=app-browser-hydration.d.ts.map