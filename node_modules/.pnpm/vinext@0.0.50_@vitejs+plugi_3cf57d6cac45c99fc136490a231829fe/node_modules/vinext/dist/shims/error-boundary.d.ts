import React from "react";
import * as _$react_jsx_runtime0 from "react/jsx-runtime";

//#region src/shims/error-boundary.d.ts
type ErrorBoundaryProps = {
  fallback: React.ComponentType<{
    error: unknown;
    reset: () => void;
  }>;
  children: React.ReactNode;
  resetKey?: string | null;
};
type CapturedError = {
  thrownValue: unknown;
};
type RedirectBoundaryState = {
  redirect: string | null;
  redirectType: "push" | "replace" | null;
};
type ErrorBoundaryInnerProps = {
  pathname: string;
} & ErrorBoundaryProps;
type ErrorBoundaryState = {
  error: CapturedError | null;
  previousPathname: string;
  previousResetKey: string | null;
};
declare class RedirectErrorBoundary extends React.Component<{
  children?: React.ReactNode;
}, RedirectBoundaryState> {
  constructor(props: {
    children?: React.ReactNode;
  });
  static getDerivedStateFromError(error: unknown): RedirectBoundaryState;
  render(): string | number | bigint | boolean | _$react_jsx_runtime0.JSX.Element | Iterable<React.ReactNode> | Promise<string | number | bigint | boolean | React.ReactPortal | React.ReactElement<unknown, string | React.JSXElementConstructor<any>> | Iterable<React.ReactNode> | null | undefined> | null | undefined;
}
declare function RedirectBoundary({
  children
}: {
  children?: React.ReactNode;
}): _$react_jsx_runtime0.JSX.Element;
/**
 * Generic ErrorBoundary used to wrap route segments with error.tsx.
 * This must be a client component since error boundaries use
 * componentDidCatch / getDerivedStateFromError.
 */
declare class ErrorBoundaryInner extends React.Component<ErrorBoundaryInnerProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryInnerProps);
  static getDerivedStateFromProps(props: ErrorBoundaryInnerProps, state: ErrorBoundaryState): ErrorBoundaryState | null;
  static getDerivedStateFromError(error: unknown): Partial<ErrorBoundaryState>;
  reset: () => void;
  render(): string | number | bigint | boolean | _$react_jsx_runtime0.JSX.Element | Iterable<React.ReactNode> | Promise<string | number | bigint | boolean | React.ReactPortal | React.ReactElement<unknown, string | React.JSXElementConstructor<any>> | Iterable<React.ReactNode> | null | undefined> | null | undefined;
}
declare function ErrorBoundary({
  fallback,
  children,
  resetKey
}: ErrorBoundaryProps): _$react_jsx_runtime0.JSX.Element;
type NotFoundBoundaryProps = {
  fallback: React.ReactNode;
  children: React.ReactNode;
  resetKey?: string | null;
};
/**
 * Wrapper that reads the current pathname and passes it to the inner class
 * component. Segment reset keys own App Router remount semantics when present.
 */
declare function NotFoundBoundary({
  fallback,
  children,
  resetKey
}: NotFoundBoundaryProps): _$react_jsx_runtime0.JSX.Element;
type ForbiddenBoundaryProps = {
  fallback: React.ReactNode;
  children: React.ReactNode;
  resetKey?: string | null;
};
type ForbiddenBoundaryInnerProps = {
  pathname: string;
} & ForbiddenBoundaryProps;
type ForbiddenBoundaryState = {
  forbidden: boolean;
  previousPathname: string;
  previousResetKey: string | null;
};
declare class ForbiddenBoundaryInner extends React.Component<ForbiddenBoundaryInnerProps, ForbiddenBoundaryState> {
  constructor(props: ForbiddenBoundaryInnerProps);
  static getDerivedStateFromProps(props: ForbiddenBoundaryInnerProps, state: ForbiddenBoundaryState): ForbiddenBoundaryState | null;
  static getDerivedStateFromError(error: unknown): Partial<ForbiddenBoundaryState>;
  render(): React.ReactNode;
}
declare function ForbiddenBoundary({
  fallback,
  children,
  resetKey
}: ForbiddenBoundaryProps): _$react_jsx_runtime0.JSX.Element;
type UnauthorizedBoundaryProps = {
  fallback: React.ReactNode;
  children: React.ReactNode;
  resetKey?: string | null;
};
type UnauthorizedBoundaryInnerProps = {
  pathname: string;
} & UnauthorizedBoundaryProps;
type UnauthorizedBoundaryState = {
  unauthorized: boolean;
  previousPathname: string;
  previousResetKey: string | null;
};
declare class UnauthorizedBoundaryInner extends React.Component<UnauthorizedBoundaryInnerProps, UnauthorizedBoundaryState> {
  constructor(props: UnauthorizedBoundaryInnerProps);
  static getDerivedStateFromProps(props: UnauthorizedBoundaryInnerProps, state: UnauthorizedBoundaryState): UnauthorizedBoundaryState | null;
  static getDerivedStateFromError(error: unknown): Partial<UnauthorizedBoundaryState>;
  render(): React.ReactNode;
}
declare function UnauthorizedBoundary({
  fallback,
  children,
  resetKey
}: UnauthorizedBoundaryProps): _$react_jsx_runtime0.JSX.Element;
type DevRecoveryBoundaryProps = {
  resetKey: number;
  onCatch?: (resetKey: number) => void;
  children?: React.ReactNode;
};
type DevRecoveryBoundaryState = {
  error: CapturedError | null;
  previousResetKey: number;
};
declare class DevRecoveryBoundary extends React.Component<DevRecoveryBoundaryProps, DevRecoveryBoundaryState> {
  constructor(props: DevRecoveryBoundaryProps);
  static getDerivedStateFromProps(props: DevRecoveryBoundaryProps, state: DevRecoveryBoundaryState): DevRecoveryBoundaryState | null;
  static getDerivedStateFromError(error: unknown): Partial<DevRecoveryBoundaryState>;
  componentDidCatch(): void;
  render(): React.ReactNode;
}
//#endregion
export { DevRecoveryBoundary, DevRecoveryBoundaryProps, ErrorBoundary, ErrorBoundaryInner, ErrorBoundaryProps, ErrorBoundaryState, ForbiddenBoundary, ForbiddenBoundaryInner, NotFoundBoundary, RedirectBoundary, RedirectErrorBoundary, UnauthorizedBoundary, UnauthorizedBoundaryInner };
//# sourceMappingURL=error-boundary.d.ts.map