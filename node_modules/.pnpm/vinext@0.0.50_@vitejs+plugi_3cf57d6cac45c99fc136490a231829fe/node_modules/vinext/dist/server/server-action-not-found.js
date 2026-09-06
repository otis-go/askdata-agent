import { NEXTJS_ACTION_NOT_FOUND_HEADER } from "./headers.js";
//#region src/server/server-action-not-found.ts
const SERVER_ACTION_NOT_FOUND_DOCS = "https://nextjs.org/docs/messages/failed-to-find-server-action";
const SERVER_ACTION_NOT_FOUND_BODY = "Server action not found.";
function getServerActionNotFoundPrefix(actionId) {
	return `Failed to find Server Action${actionId ? ` "${actionId}"` : ""}.`;
}
function getServerActionNotFoundMessage(actionId) {
	return `${getServerActionNotFoundPrefix(actionId)} This request might be from an older or newer deployment.\nRead more: ${SERVER_ACTION_NOT_FOUND_DOCS}`;
}
function getServerActionNotFoundClientMessage(actionId) {
	return `Server Action "${actionId}" was not found on the server. \nRead more: ${SERVER_ACTION_NOT_FOUND_DOCS}`;
}
function getUnknownMessage(error) {
	if (error instanceof Error) return error.message;
	return typeof error === "string" ? error : "";
}
function isServerActionNotFoundError(error, actionId) {
	const message = getUnknownMessage(error);
	if (!message) return false;
	if (!actionId) return message.startsWith("Failed to find Server Action");
	if (message.startsWith(getServerActionNotFoundPrefix(actionId))) return true;
	return Boolean(actionId && message.includes(`[vite-rsc] invalid server reference '${actionId}'`));
}
function createServerActionNotFoundResponse() {
	return new Response(SERVER_ACTION_NOT_FOUND_BODY, {
		status: 404,
		headers: {
			[NEXTJS_ACTION_NOT_FOUND_HEADER]: "1",
			"content-type": "text/plain"
		}
	});
}
function isServerActionNotFoundResponse(response) {
	return response.headers.get(NEXTJS_ACTION_NOT_FOUND_HEADER) === "1";
}
//#endregion
export { createServerActionNotFoundResponse, getServerActionNotFoundClientMessage, getServerActionNotFoundMessage, isServerActionNotFoundError, isServerActionNotFoundResponse };

//# sourceMappingURL=server-action-not-found.js.map