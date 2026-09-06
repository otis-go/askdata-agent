//#region src/utils/hash.ts
/**
* FNV-1a hash producing a 64-bit result (two 32-bit rounds with different seeds).
* Used for deterministic key generation where collisions must be rare.
*/
function fnv1a64(input) {
	let h1 = 2166136261;
	for (let i = 0; i < input.length; i++) {
		h1 ^= input.charCodeAt(i);
		h1 = h1 * 16777619 >>> 0;
	}
	let h2 = 84696351;
	for (let i = 0; i < input.length; i++) {
		h2 ^= input.charCodeAt(i);
		h2 = h2 * 16777619 >>> 0;
	}
	return h1.toString(36) + h2.toString(36);
}
//#endregion
export { fnv1a64 };

//# sourceMappingURL=hash.js.map