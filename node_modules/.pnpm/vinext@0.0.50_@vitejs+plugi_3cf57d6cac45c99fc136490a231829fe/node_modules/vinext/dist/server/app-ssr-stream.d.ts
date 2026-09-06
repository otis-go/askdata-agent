//#region src/server/app-ssr-stream.d.ts
type RscEmbedTransform = {
  flush(): string;
  finalize(): Promise<string>; /** Resolves when all raw bytes from the embed stream have been read. */
  getRawBuffer(): Promise<ArrayBuffer>;
};
type HtmlInsertion = string | (() => string);
/**
 * Fix invalid preload "as" values in RSC Flight hint lines before they reach
 * the client. React Flight emits HL hints with as="stylesheet" for CSS, but
 * the HTML spec requires as="style" for <link rel="preload">.
 */
declare function fixFlightHints(text: string): string;
/**
 * Create a helper that progressively embeds RSC chunks as inline <script> tags.
 * The browser entry turns the embedded text chunks back into Uint8Array data.
 */
declare function createRscEmbedTransform(embedStream: ReadableStream<Uint8Array>, scriptNonce?: string): RscEmbedTransform;
/**
 * Fix invalid preload "as" values in server-rendered HTML.
 * React Fizz emits <link rel="preload" as="stylesheet"> for CSS, but the
 * HTML spec requires as="style" for <link rel="preload">.
 */
declare function fixPreloadAs(html: string): string;
/**
 * Create the tick-buffered HTML transform that injects RSC scripts between
 * React Fizz flush cycles without corrupting split HTML chunks.
 */
declare function createTickBufferedTransform(rscEmbed: RscEmbedTransform, injectHTML?: HtmlInsertion): TransformStream<Uint8Array, Uint8Array>;
//#endregion
export { createRscEmbedTransform, createTickBufferedTransform, fixFlightHints, fixPreloadAs };
//# sourceMappingURL=app-ssr-stream.d.ts.map