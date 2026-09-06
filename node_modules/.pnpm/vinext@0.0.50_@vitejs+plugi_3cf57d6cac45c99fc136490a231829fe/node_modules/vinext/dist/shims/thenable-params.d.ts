//#region src/shims/thenable-params.d.ts
declare const WELL_KNOWN_PROPERTIES: readonly ["hasOwnProperty", "isPrototypeOf", "propertyIsEnumerable", "toString", "valueOf", "toLocaleString", "then", "catch", "finally", "status", "value", "error", "displayName", "_debugInfo", "toJSON", "$$typeof", "__esModule", "@@iterator"];
type WellKnownProperty = (typeof WELL_KNOWN_PROPERTIES)[number];
type ThenableParams<T extends Record<string, unknown>> = Promise<T> & Omit<T, WellKnownProperty>;
declare function makeThenableParams<T extends Record<string, unknown>>(obj: T): ThenableParams<T>;
//#endregion
export { ThenableParams, makeThenableParams };
//# sourceMappingURL=thenable-params.d.ts.map