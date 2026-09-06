//#region src/server/server-action-not-found.d.ts
declare function getServerActionNotFoundMessage(actionId: string | null): string;
declare function getServerActionNotFoundClientMessage(actionId: string): string;
declare function isServerActionNotFoundError(error: unknown, actionId: string | null): boolean;
declare function createServerActionNotFoundResponse(): Response;
declare function isServerActionNotFoundResponse(response: Pick<Response, "headers">): boolean;
//#endregion
export { createServerActionNotFoundResponse, getServerActionNotFoundClientMessage, getServerActionNotFoundMessage, isServerActionNotFoundError, isServerActionNotFoundResponse };
//# sourceMappingURL=server-action-not-found.d.ts.map