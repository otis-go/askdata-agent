import { ComponentType } from "react";

//#region src/shims/dynamic.d.ts
type DynamicLoadingProps = {
  error?: Error | null;
  isLoading?: boolean;
  pastDelay?: boolean;
  retry?: () => void;
  timedOut?: boolean;
};
type ComponentModule<P> = {
  default: ComponentType<P>;
};
type LoaderComponent<P> = Promise<ComponentModule<P> | ComponentType<P>>;
type LoaderFn<P> = () => LoaderComponent<P>;
type DynamicOptions<P> = {
  loading?: ComponentType<DynamicLoadingProps>;
  loader?: Loader<P>;
  ssr?: boolean;
};
type Loader<P> = LoaderFn<P> | LoaderComponent<P>;
type DynamicInput<P> = DynamicOptions<P> | Loader<P>;
/**
 * Wait for all pending dynamic() preloads to resolve, then clear the queue.
 * Called by the Pages Router SSR handler before rendering.
 * No-op for the App Router path which uses React.lazy + Suspense.
 */
declare function flushPreloads(): Promise<void[]>;
declare function dynamic<P extends object = object>(dynamicInput: DynamicInput<P>, options?: DynamicOptions<P>): ComponentType<P>;
//#endregion
export { dynamic as default, flushPreloads };
//# sourceMappingURL=dynamic.d.ts.map