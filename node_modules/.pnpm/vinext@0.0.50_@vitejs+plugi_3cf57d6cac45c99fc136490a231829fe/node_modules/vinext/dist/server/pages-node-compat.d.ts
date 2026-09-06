import { PagesBodyParseError } from "./pages-media-type.js";

//#region src/server/pages-node-compat.d.ts
type PagesRequestQuery = Record<string, string | string[]>;
type PagesReqResRequest = {
  method: string;
  url: string;
  headers: Record<string, string>;
  query: PagesRequestQuery;
  body: unknown;
  cookies: Record<string, string>;
};
type PagesReqResHeaders = {
  [key: string]: string | number | boolean | string[];
};
type PagesReqResResponse = {
  statusCode: number;
  readonly headersSent: boolean;
  writeHead: (code: number, headers?: PagesReqResHeaders) => PagesReqResResponse;
  setHeader: (name: string, value: string | number | boolean | string[]) => PagesReqResResponse;
  getHeader: (name: string) => string | number | boolean | string[] | undefined;
  end: (data?: BodyInit | null) => void;
  status: (code: number) => PagesReqResResponse;
  json: (data: unknown) => void;
  send: (data: unknown) => void;
  redirect: (statusOrUrl: number | string, url?: string) => void;
  getHeaders: () => PagesReqResHeaders;
};
type CreatePagesReqResOptions = {
  body: unknown;
  query: PagesRequestQuery;
  request: Request;
  url: string;
};
type CreatePagesReqResResult = {
  req: PagesReqResRequest;
  res: PagesReqResResponse;
  responsePromise: Promise<Response>;
};
declare function parsePagesApiBody(request: Request, maxBytes?: number): Promise<unknown>;
declare function createPagesReqRes(options: CreatePagesReqResOptions): CreatePagesReqResResult;
//#endregion
export { PagesBodyParseError as PagesApiBodyParseError, PagesReqResHeaders, PagesReqResRequest, PagesReqResResponse, PagesRequestQuery, createPagesReqRes, parsePagesApiBody };
//# sourceMappingURL=pages-node-compat.d.ts.map