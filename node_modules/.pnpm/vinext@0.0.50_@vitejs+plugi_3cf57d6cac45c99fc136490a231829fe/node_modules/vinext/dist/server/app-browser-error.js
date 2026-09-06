//#region src/server/app-browser-error.ts
function createOnUncaughtError(getRecoveryHref) {
	return (error, errorInfo) => {
		console.error(error);
		if (errorInfo?.componentStack) console.error("The above error occurred in a React component:\n" + errorInfo.componentStack);
		const recoveryHref = getRecoveryHref();
		if (recoveryHref !== null) window.location.assign(recoveryHref);
	};
}
//#endregion
export { createOnUncaughtError };

//# sourceMappingURL=app-browser-error.js.map