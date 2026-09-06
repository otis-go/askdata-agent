//#region src/utils/hash.d.ts
/**
 * FNV-1a hash producing a 64-bit result (two 32-bit rounds with different seeds).
 * Used for deterministic key generation where collisions must be rare.
 */
declare function fnv1a64(input: string): string;
//#endregion
export { fnv1a64 };
//# sourceMappingURL=hash.d.ts.map