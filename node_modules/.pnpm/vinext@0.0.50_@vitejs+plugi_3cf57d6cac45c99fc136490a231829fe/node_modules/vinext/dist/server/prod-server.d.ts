import { StaticFileCache } from "./static-file-cache.js";
import * as _$node_http0 from "node:http";
import { IncomingMessage, ServerResponse } from "node:http";

//#region src/server/prod-server.d.ts
type ProdServerOptions = {
  /** Port to listen on */port?: number; /** Host to bind to */
  host?: string; /** Path to the build output directory */
  outDir?: string; /** Disable compression (default: false) */
  noCompression?: boolean;
  /**
   * Narrow startup context for callers that need a more precise log line.
   * Omitted for normal `vinext start` so the existing production-server output
   * remains stable.
   */
  purpose?: "prerender";
};
/** Content types that benefit from compression. */
declare const COMPRESSIBLE_TYPES: Set<string>;
/** Minimum size threshold for compression (in bytes). Below this, compression overhead isn't worth it. */
declare const COMPRESS_THRESHOLD = 1024;
declare function negotiateEncoding(req: IncomingMessage): "zstd" | "br" | "gzip" | "deflate" | null;
/**
 * Merge middleware headers and a Web Response's headers into a single
 * record suitable for Node.js `res.writeHead()`. Uses `getSetCookie()`
 * to preserve multiple Set-Cookie values instead of flattening them.
 */
declare function mergeResponseHeaders(middlewareHeaders: Record<string, string | string[]>, response: Response): Record<string, string | string[]>;
/**
 * Merge middleware/config headers and an optional status override into a new
 * Web Response while preserving the original body stream when allowed.
 * Keep this in sync with server/worker-utils.ts and the generated copy in
 * deploy.ts.
 */
declare function mergeWebResponse(middlewareHeaders: Record<string, string | string[]>, response: Response, statusOverride?: number): Response;
/**
 * Send a compressed response if the content type is compressible and the
 * client supports compression. Otherwise send uncompressed.
 */
declare function sendCompressed(req: IncomingMessage, res: ServerResponse, body: string | Buffer, contentType: string, statusCode: number, extraHeaders?: Record<string, string | string[]>, compress?: boolean, statusText?: string): void;
/**
 * Try to serve a static file from the client build directory.
 *
 * When a `StaticFileCache` is provided, lookups are pure in-memory Map.get()
 * with zero filesystem calls. Precompressed .br/.gz/.zst variants (generated at
 * build time) are served directly — no per-request compression needed for
 * hashed assets.
 *
 * Without a cache, falls back to async filesystem probing (still non-blocking,
 * unlike the old sync existsSync/statSync approach).
 */
declare function tryServeStatic(req: IncomingMessage, res: ServerResponse, clientDir: string, pathname: string, compress: boolean, cache?: StaticFileCache, extraHeaders?: Record<string, string | string[]>, statusCode?: number): Promise<boolean>;
/**
 * Resolve the host for a request, ignoring X-Forwarded-Host to prevent
 * host header poisoning attacks (open redirects, cache poisoning).
 *
 * X-Forwarded-Host is only trusted when the VINEXT_TRUSTED_HOSTS env var
 * lists the forwarded host value. Without this, an attacker can send
 * X-Forwarded-Host: evil.com and poison any redirect that resolves
 * against request.url.
 *
 * On Cloudflare Workers, X-Forwarded-Host is always set by Cloudflare
 * itself, so this is only a concern for the Node.js prod-server.
 */
declare function resolveHost(req: IncomingMessage, fallback: string): string;
/** Hosts that are allowed as X-Forwarded-Host values (stored lowercase). */
declare const trustedHosts: Set<string>;
/**
 * Whether to trust X-Forwarded-Proto from upstream proxies.
 * Enabled when VINEXT_TRUST_PROXY=1 or when VINEXT_TRUSTED_HOSTS is set
 * (having trusted hosts implies a trusted proxy).
 */
declare const trustProxy: boolean;
/**
 * Convert a Node.js IncomingMessage to a Web Request object.
 *
 * When `urlOverride` is provided, it is used as the path + query string
 * instead of `req.url`. This avoids redundant path normalization when the
 * caller has already decoded and normalized the pathname (e.g. the App
 * Router prod server normalizes before static-asset lookup, and can pass
 * the result here so the downstream RSC handler doesn't re-normalize).
 */
declare function nodeToWebRequest(req: IncomingMessage, urlOverride?: string): Request;
/**
 * Stream a Web Response back to a Node.js ServerResponse.
 * Supports streaming compression for SSR responses.
 */
declare function sendWebResponse(webResponse: Response, req: IncomingMessage, res: ServerResponse, compress: boolean): Promise<void>;
/**
 * Start the production server.
 *
 * Automatically detects whether the build is App Router (dist/server/index.js) or
 * Pages Router (dist/server/entry.js) and configures the appropriate handler.
 */
declare function startProdServer(options?: ProdServerOptions): Promise<{
  server: _$node_http0.Server<typeof IncomingMessage, typeof ServerResponse>;
  port: number;
}>;
//#endregion
export { COMPRESSIBLE_TYPES, COMPRESS_THRESHOLD, ProdServerOptions, mergeResponseHeaders, mergeWebResponse, negotiateEncoding, nodeToWebRequest, resolveHost, sendCompressed, sendWebResponse, startProdServer, trustProxy, trustedHosts, tryServeStatic };
//# sourceMappingURL=prod-server.d.ts.map