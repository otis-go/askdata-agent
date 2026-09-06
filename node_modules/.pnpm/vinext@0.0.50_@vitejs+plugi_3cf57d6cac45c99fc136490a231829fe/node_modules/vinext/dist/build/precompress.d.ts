//#region src/build/precompress.d.ts
type PrecompressResult = {
  filesCompressed: number;
  totalOriginalBytes: number; /** Sum of brotli-compressed sizes (used for compression ratio reporting). */
  totalBrotliBytes: number;
};
/**
 * Precompress all compressible hashed assets under `clientDir/assets/`.
 *
 * Writes `.br`, `.gz`, and `.zst` files alongside each original.
 * Safe to re-run — overwrites existing compressed variants with identical
 * output, and never compresses `.br`, `.gz`, or `.zst` files themselves.
 */
declare function precompressAssets(clientDir: string, onProgress?: (completed: number, total: number, file: string) => void): Promise<PrecompressResult>;
//#endregion
export { precompressAssets };
//# sourceMappingURL=precompress.d.ts.map