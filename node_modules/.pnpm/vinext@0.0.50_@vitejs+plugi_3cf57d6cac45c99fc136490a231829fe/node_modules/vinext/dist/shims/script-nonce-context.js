import React from "react";
//#region src/shims/script-nonce-context.tsx
const ScriptNonceContext = React.createContext(void 0);
function ScriptNonceProvider(props) {
	return React.createElement(ScriptNonceContext.Provider, { value: props.nonce }, props.children);
}
function withScriptNonce(element, nonce) {
	if (!nonce) return element;
	return React.createElement(ScriptNonceProvider, { nonce }, element);
}
function useScriptNonce() {
	return React.useContext(ScriptNonceContext);
}
//#endregion
export { ScriptNonceContext, ScriptNonceProvider, useScriptNonce, withScriptNonce };

//# sourceMappingURL=script-nonce-context.js.map