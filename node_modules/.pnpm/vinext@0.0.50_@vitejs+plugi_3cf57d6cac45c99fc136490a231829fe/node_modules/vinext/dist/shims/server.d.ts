//#region src/shims/server.d.ts
/**
 * next/server shim
 *
 * Provides NextRequest, NextResponse, and related types that work with
 * standard Web APIs (Request/Response). This means they work on Node,
 * Cloudflare Workers, Deno, and any WinterCG-compatible runtime.
 *
 * This is a pragmatic subset — we implement the most commonly used APIs
 * rather than bug-for-bug parity with Next.js internals.
 */
declare class NextRequest extends Request {
  private _nextUrl;
  private _url;
  private _cookies;
  constructor(input: URL | RequestInfo, init?: RequestInit & {
    nextConfig?: {
      basePath?: string;
      i18n?: {
        locales: string[];
        defaultLocale: string;
      };
    };
  });
  get nextUrl(): NextURL;
  get url(): string;
  get cookies(): RequestCookies;
  /**
   * Client IP address. Prefers Cloudflare's trusted CF-Connecting-IP header
   * over the spoofable X-Forwarded-For. Returns undefined if unavailable.
   */
  get ip(): string | undefined;
  /**
   * Geolocation data. Platform-dependent (e.g., Cloudflare, Vercel).
   * Returns undefined if not available.
   */
  get geo(): {
    city?: string;
    country?: string;
    region?: string;
    latitude?: string;
    longitude?: string;
  } | undefined;
  /**
   * The build ID of the Next.js application.
   * Delegates to `nextUrl.buildId` to match Next.js API surface.
   * Can be used in middleware to detect deployment skew between client and server.
   */
  get buildId(): string | undefined;
}
declare class NextResponse<_Body = unknown> extends Response {
  private _cookies;
  constructor(body?: BodyInit | null, init?: ResponseInit);
  get cookies(): ResponseCookies;
  /**
   * Create a JSON response.
   */
  static json<JsonBody>(body: JsonBody, init?: ResponseInit): NextResponse<JsonBody>;
  /**
   * Create a redirect response.
   */
  static redirect(url: string | URL, init?: number | ResponseInit): NextResponse;
  /**
   * Create a rewrite response (middleware pattern).
   * Sets the x-middleware-rewrite header.
   */
  static rewrite(destination: string | URL, init?: MiddlewareResponseInit): NextResponse;
  /**
   * Continue to the next handler (middleware pattern).
   * Sets the x-middleware-next header.
   */
  static next(init?: MiddlewareResponseInit): NextResponse;
}
type NextURLConfig = {
  basePath?: string;
  nextConfig?: {
    i18n?: {
      locales: string[];
      defaultLocale: string;
    };
  };
};
declare class NextURL {
  /** Internal URL stores the pathname WITHOUT basePath or locale prefix. */
  private _url;
  private _basePath;
  private _locale;
  private _defaultLocale;
  private _locales;
  constructor(input: string | URL, base?: string | URL, config?: NextURLConfig);
  /** Strip basePath prefix from the internal pathname. */
  private _stripBasePath;
  /** Extract locale from pathname, stripping it from the internal URL. */
  private _analyzeLocale;
  /**
   * Reconstruct the full pathname with basePath + locale prefix.
   * Mirrors Next.js's internal formatPathname().
   */
  private _formatPathname;
  get href(): string;
  set href(value: string);
  get origin(): string;
  get protocol(): string;
  set protocol(value: string);
  get username(): string;
  set username(value: string);
  get password(): string;
  set password(value: string);
  get host(): string;
  set host(value: string);
  get hostname(): string;
  set hostname(value: string);
  get port(): string;
  set port(value: string);
  /** Returns the pathname WITHOUT basePath or locale prefix. */
  get pathname(): string;
  set pathname(value: string);
  get search(): string;
  set search(value: string);
  get searchParams(): URLSearchParams;
  get hash(): string;
  set hash(value: string);
  get basePath(): string;
  set basePath(value: string);
  get locale(): string;
  set locale(value: string | undefined);
  get defaultLocale(): string | undefined;
  get locales(): string[] | undefined;
  clone(): NextURL;
  toString(): string;
  /**
   * The build ID of the Next.js application.
   * Set from `generateBuildId` in next.config.js, or a random UUID if not configured.
   * Can be used in middleware to detect deployment skew between client and server.
   * Matches the Next.js API: `request.nextUrl.buildId`.
   */
  get buildId(): string | undefined;
}
type CookieEntry = {
  name: string;
  value: string;
};
declare class RequestCookies {
  private _headers;
  private _parsed;
  constructor(headers: Headers);
  get(name: string): CookieEntry | undefined;
  getAll(nameOrOptions?: string | CookieEntry): CookieEntry[];
  has(name: string): boolean;
  set(nameOrOptions: string | CookieEntry, value?: string): this;
  delete(names: string | string[]): boolean | boolean[];
  clear(): this;
  get size(): number;
  toString(): string;
  private _serialize;
  private _syncHeader;
  [Symbol.iterator](): IterableIterator<[string, CookieEntry]>;
}
declare function sealRequestHeaders(headers: Headers): Headers;
declare function sealRequestCookies(cookies: RequestCookies): RequestCookies;
declare class ResponseCookies {
  private _headers;
  /** Internal map keyed by cookie name — single source of truth. */
  private _parsed;
  constructor(headers: Headers);
  set(...args: [name: string, value: string, options?: CookieOptions] | [options: CookieOptions & {
    name: string;
    value: string;
  }]): this;
  get(...args: [name: string] | [options: {
    name: string;
  }]): CookieEntry | undefined;
  has(name: string): boolean;
  getAll(...args: [name: string] | [options: {
    name: string;
  }] | []): CookieEntry[];
  delete(...args: [name: string] | [options: Omit<CookieOptions & {
    name: string;
  }, "maxAge" | "expires">]): this;
  [Symbol.iterator](): IterableIterator<[string, CookieEntry]>;
  /** Delete all Set-Cookie headers and re-append from the internal map. */
  private _syncHeaders;
}
type CookieOptions = {
  path?: string;
  domain?: string;
  maxAge?: number;
  expires?: Date;
  httpOnly?: boolean;
  secure?: boolean;
  sameSite?: "Strict" | "Lax" | "None";
};
type MiddlewareResponseInit = {
  request?: {
    headers?: Headers;
  };
} & ResponseInit;
type NextMiddlewareResult = NextResponse | Response | null | undefined | void;
type NextMiddleware = (request: NextRequest, event: NextFetchEvent) => NextMiddlewareResult | Promise<NextMiddlewareResult>;
/**
 * Minimal NextFetchEvent — extends FetchEvent where available,
 * otherwise provides the waitUntil pattern standalone.
 */
declare class NextFetchEvent {
  sourcePage: string;
  private _waitUntilPromises;
  constructor(params: {
    page: string;
  });
  waitUntil(promise: Promise<unknown>): void;
  get waitUntilPromises(): Promise<unknown>[];
  /** Drain all waitUntil promises. Returns a single promise that settles when all are done. */
  drainWaitUntil(): Promise<PromiseSettledResult<unknown>[]>;
}
/**
 * Parse user agent string. Minimal implementation — for full UA parsing,
 * apps should use a dedicated library like `ua-parser-js`.
 */
declare function userAgentFromString(ua: string | undefined): UserAgent;
declare function userAgent({
  headers
}: {
  headers: Headers;
}): UserAgent;
type UserAgent = {
  isBot: boolean;
  ua: string;
  browser: {
    name?: string;
    version?: string;
    major?: string;
  };
  device: {
    model?: string;
    type?: string;
    vendor?: string;
  };
  engine: {
    name?: string;
    version?: string;
  };
  os: {
    name?: string;
    version?: string;
  };
  cpu: {
    architecture?: string;
  };
};
/**
 * after() — schedule work after the response is sent.
 *
 * Uses the platform's `waitUntil` (via the per-request ExecutionContext) when
 * available so the task survives past the response on Cloudflare Workers.
 * Falls back to a fire-and-forget microtask on runtimes without an execution
 * context (e.g. Node.js dev server).
 *
 * Throws when called inside a cached scope — request-specific
 * side-effects must not leak into cached results.
 */
declare function after<T>(task: Promise<T> | (() => T | Promise<T>)): void;
/**
 * connection() — signals that the response requires a live connection
 * (not a static/cached response). Opts the page out of ISR caching
 * and sets Cache-Control: no-store on the response.
 */
declare function connection(): Promise<void>;
/**
 * URLPattern re-export — used in middleware for route matching.
 * Available natively in Node 20+, Cloudflare Workers, Deno.
 * Falls back to urlpattern-polyfill if the global is not available.
 */
declare const URLPattern: typeof globalThis.URLPattern;
//#endregion
export { MiddlewareResponseInit, NextFetchEvent, NextMiddleware, NextMiddlewareResult, NextRequest, NextResponse, NextURL, NextURLConfig, RequestCookies, ResponseCookies, URLPattern, UserAgent, after, connection, sealRequestCookies, sealRequestHeaders, userAgent, userAgentFromString };
//# sourceMappingURL=server.d.ts.map