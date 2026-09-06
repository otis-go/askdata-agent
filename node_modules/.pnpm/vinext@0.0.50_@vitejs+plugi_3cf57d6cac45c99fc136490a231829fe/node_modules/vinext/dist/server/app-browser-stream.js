//#region src/server/app-browser-stream.ts
function getVinextBrowserGlobal() {
	return globalThis;
}
function createUnexpectedRscStreamCloseError() {
	return /* @__PURE__ */ new Error("The connection to the page was unexpectedly closed, possibly due to the stop button being clicked, loss of Wi-Fi, or an unstable internet connection.");
}
/**
* Convert embedded text chunks back to a ReadableStream of Uint8Array chunks.
*/
function chunksToReadableStream(chunks) {
	const encoder = new TextEncoder();
	return new ReadableStream({ start(controller) {
		for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
		controller.close();
	} });
}
/**
* Create a ReadableStream from progressively-embedded RSC chunks.
*
* The server pushes chunks into `__VINEXT_RSC_CHUNKS__` via inline <script>
* tags. We monkey-patch `push()` so new chunks stream to React immediately
* instead of polling with setTimeout.
*/
function createProgressiveRscStream() {
	const encoder = new TextEncoder();
	return new ReadableStream({ start(controller) {
		const vinext = getVinextBrowserGlobal();
		const initialChunks = vinext.__VINEXT_RSC_CHUNKS__ ?? [];
		for (const chunk of initialChunks) controller.enqueue(encoder.encode(chunk));
		if (vinext.__VINEXT_RSC_DONE__) {
			controller.close();
			return;
		}
		let closed = false;
		let cancelDocumentCompletionCheck;
		const cancelPendingDocumentCompletionCheck = () => {
			const cancel = cancelDocumentCompletionCheck;
			cancelDocumentCompletionCheck = void 0;
			cancel?.();
		};
		const closeOnce = () => {
			if (!closed) {
				closed = true;
				cancelPendingDocumentCompletionCheck();
				controller.close();
			}
		};
		const errorOnce = () => {
			if (!closed) {
				closed = true;
				cancelPendingDocumentCompletionCheck();
				controller.error(createUnexpectedRscStreamCloseError());
			}
		};
		const arr = vinext.__VINEXT_RSC_CHUNKS__ ??= [];
		arr.push = function(...chunks) {
			const length = Array.prototype.push.apply(this, chunks);
			if (closed) return length;
			for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
			if (vinext.__VINEXT_RSC_DONE__) closeOnce();
			return length;
		};
		if (typeof document !== "undefined") if (document.readyState === "loading") {
			document.addEventListener("DOMContentLoaded", errorOnce);
			cancelDocumentCompletionCheck = () => document.removeEventListener("DOMContentLoaded", errorOnce);
		} else {
			const timeoutId = setTimeout(errorOnce);
			cancelDocumentCompletionCheck = () => clearTimeout(timeoutId);
		}
	} });
}
//#endregion
export { chunksToReadableStream, createProgressiveRscStream, getVinextBrowserGlobal };

//# sourceMappingURL=app-browser-stream.js.map