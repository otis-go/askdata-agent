//#region src/server/image-optimization.d.ts
/**
 * Image optimization request handler.
 *
 * Handles `/_vinext/image?url=...&w=...&q=...` requests. In production
 * on Cloudflare Workers, uses the Images binding (`env.IMAGES`) to
 * resize and transcode on the fly. On other runtimes (Node.js dev/prod
 * server), serves the original file as a passthrough with appropriate
 * Cache-Control headers.
 *
 * Format negotiation: inspects the `Accept` header and serves AVIF, WebP,
 * or JPEG depending on client support.
 *
 * Security: All image responses include Content-Security-Policy and
 * X-Content-Type-Options headers to prevent XSS via SVG or Content-Type
 * spoofing. SVG content is blocked by default (following Next.js behavior).
 * When `dangerouslyAllowSVG` is enabled in next.config.js, SVGs are served
 * as-is (no transformation) with security headers applied.
 */
/** The pathname that triggers image optimization. */
declare const IMAGE_OPTIMIZATION_PATH = "/_vinext/image";
/**
 * Image security configuration from next.config.js `images` section.
 * Controls SVG handling and security headers for the image endpoint.
 */
type ImageConfig = {
  /** Allow SVG through the image optimization endpoint. Default: false. */dangerouslyAllowSVG?: boolean;
  /**
   * Allow image optimization for hostnames that resolve to private IP addresses.
   * Default: false.
   *
   * Note: This field is currently reserved for future server-side remote-image
   * fetching. vinext's image optimization endpoint only serves local files, so
   * there is no active server-side SSRF vector — the flag is consumed client-side
   * via the image shim instead.
   */
  dangerouslyAllowLocalIP?: boolean; /** Content-Disposition header value. Default: "inline". */
  contentDispositionType?: "inline" | "attachment"; /** Content-Security-Policy header value. Default: "script-src 'none'; frame-src 'none'; sandbox;" */
  contentSecurityPolicy?: string;
};
/**
 * Next.js default device sizes and image sizes.
 * These are the allowed widths for image optimization when no custom
 * config is provided. Matches Next.js defaults exactly.
 */
declare const DEFAULT_DEVICE_SIZES: number[];
declare const DEFAULT_IMAGE_SIZES: number[];
/**
 * Parse and validate image optimization query parameters.
 * Returns null if the request is malformed.
 *
 * When `allowedWidths` is provided, the width must be 0 (no resize) or
 * exactly match one of the allowed values. This matches Next.js behavior
 * where only configured deviceSizes and imageSizes are accepted.
 *
 * When `allowedWidths` is not provided, any width from 0 to ABSOLUTE_MAX_WIDTH
 * is accepted (backwards-compatible fallback).
 */
declare function parseImageParams(url: URL, allowedWidths?: number[]): {
  imageUrl: string;
  width: number;
  quality: number;
} | null;
/**
 * Negotiate the best output format based on the Accept header.
 * Returns an IANA media type.
 */
declare function negotiateImageFormat(acceptHeader: string | null): string;
/**
 * Standard Cache-Control header for optimized images.
 * Optimized images are immutable because the URL encodes the transform params.
 */
declare const IMAGE_CACHE_CONTROL = "public, max-age=31536000, immutable";
/**
 * Content-Security-Policy for image optimization responses.
 * Blocks script execution and framing to prevent XSS via SVG or other
 * active content that might be served through the image endpoint.
 * Matches Next.js default: script-src 'none'; frame-src 'none'; sandbox;
 */
declare const IMAGE_CONTENT_SECURITY_POLICY = "script-src 'none'; frame-src 'none'; sandbox;";
/**
 * Check if a Content-Type header value is a safe image type.
 * Returns false for SVG (unless dangerouslyAllowSVG is true), HTML, or any non-image type.
 */
declare function isSafeImageContentType(contentType: string | null, dangerouslyAllowSVG?: boolean): boolean;
/**
 * Handlers for image optimization I/O operations.
 * Workers provide these callbacks to adapt their specific bindings.
 */
type ImageHandlers = {
  /** Fetch the source image from storage (e.g., Cloudflare ASSETS binding). */fetchAsset: (path: string, request: Request) => Promise<Response>; /** Optional: Transform the image (resize, format, quality). */
  transformImage?: (body: ReadableStream, options: {
    width: number;
    format: string;
    quality: number;
  }) => Promise<Response>;
};
/**
 * Handle image optimization requests.
 *
 * Parses and validates the request, fetches the source image via the provided
 * handlers, optionally transforms it, and returns the response with appropriate
 * cache headers.
 */
declare function handleImageOptimization(request: Request, handlers: ImageHandlers, allowedWidths?: number[], imageConfig?: ImageConfig): Promise<Response>;
//#endregion
export { DEFAULT_DEVICE_SIZES, DEFAULT_IMAGE_SIZES, IMAGE_CACHE_CONTROL, IMAGE_CONTENT_SECURITY_POLICY, IMAGE_OPTIMIZATION_PATH, ImageConfig, ImageHandlers, handleImageOptimization, isSafeImageContentType, negotiateImageFormat, parseImageParams };
//# sourceMappingURL=image-optimization.d.ts.map