import React from "react";

//#region src/shims/script-nonce-context.d.ts
declare const ScriptNonceContext: React.Context<string | undefined>;
declare function ScriptNonceProvider(props: React.PropsWithChildren<{
  nonce?: string;
}>): React.ReactElement;
declare function withScriptNonce(element: React.ReactElement, nonce?: string): React.ReactElement;
declare function useScriptNonce(): string | undefined;
//#endregion
export { ScriptNonceContext, ScriptNonceProvider, useScriptNonce, withScriptNonce };
//# sourceMappingURL=script-nonce-context.d.ts.map