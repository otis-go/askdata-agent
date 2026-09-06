//#region src/utils/cache-control-metadata.d.ts
declare function isUnknownRecord(value: unknown): value is Record<string, unknown>;
declare function readCacheControlNumberField(ctx: Record<string, unknown> | undefined, field: string): number | undefined;
//#endregion
export { isUnknownRecord, readCacheControlNumberField };
//# sourceMappingURL=cache-control-metadata.d.ts.map