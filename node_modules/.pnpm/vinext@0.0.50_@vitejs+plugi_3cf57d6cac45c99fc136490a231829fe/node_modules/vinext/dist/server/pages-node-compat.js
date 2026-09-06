import { parseCookies } from "../config/config-matchers.js";
import { PagesBodyParseError, getMediaType, isJsonMediaType } from "./pages-media-type.js";
import { readStreamAsTextWithLimit } from "../utils/text-stream.js";
import { decode } from "node:querystring";
//#region src/server/pages-node-compat.ts
const MAX_PAGES_API_BODY_SIZE = 1 * 1024 * 1024;
async function readPagesRequestBodyWithLimit(request, maxBytes) {
	if (!request.body) return "";
	return readStreamAsTextWithLimit(request.body, maxBytes, () => {
		throw new PagesBodyParseError("Request body too large", 413);
	});
}
async function parsePagesApiBody(request, maxBytes = MAX_PAGES_API_BODY_SIZE) {
	if (Number.parseInt(request.headers.get("content-length") || "0", 10) > maxBytes) throw new PagesBodyParseError("Request body too large", 413);
	let rawBody = "";
	try {
		rawBody = await readPagesRequestBodyWithLimit(request, maxBytes);
	} catch (err) {
		if (err instanceof PagesBodyParseError) throw err;
		throw new PagesBodyParseError("Request body too large", 413);
	}
	const mediaType = getMediaType(request.headers.get("content-type"));
	if (!rawBody) return isJsonMediaType(mediaType) ? {} : mediaType === "application/x-www-form-urlencoded" ? decode(rawBody) : void 0;
	if (isJsonMediaType(mediaType)) try {
		return JSON.parse(rawBody);
	} catch {
		throw new PagesBodyParseError("Invalid JSON", 400);
	}
	if (mediaType === "application/x-www-form-urlencoded") return decode(rawBody);
	return rawBody;
}
function createPagesReqRes(options) {
	const headersObj = {};
	for (const [key, value] of options.request.headers) headersObj[key.toLowerCase()] = value;
	const req = {
		method: options.request.method,
		url: options.url,
		headers: headersObj,
		query: options.query,
		body: options.body,
		cookies: parseCookies(options.request.headers.get("cookie"))
	};
	let resStatusCode = 200;
	const resHeaders = {};
	const setCookieHeaders = [];
	let resBody = null;
	let ended = false;
	let resolveResponse;
	const responsePromise = new Promise((resolve) => {
		resolveResponse = resolve;
	});
	const res = {
		get statusCode() {
			return resStatusCode;
		},
		set statusCode(code) {
			resStatusCode = code;
		},
		get headersSent() {
			return ended;
		},
		writeHead(code, headers) {
			resStatusCode = code;
			if (headers) for (const [key, value] of Object.entries(headers)) if (key.toLowerCase() === "set-cookie") if (Array.isArray(value)) setCookieHeaders.push(...value.map(String));
			else setCookieHeaders.push(String(value));
			else resHeaders[key.toLowerCase()] = Array.isArray(value) ? value.join(", ") : value;
			return res;
		},
		setHeader(name, value) {
			if (name.toLowerCase() === "set-cookie") {
				setCookieHeaders.length = 0;
				if (Array.isArray(value)) setCookieHeaders.push(...value.map(String));
				else setCookieHeaders.push(String(value));
			} else resHeaders[name.toLowerCase()] = Array.isArray(value) ? value.join(", ") : value;
			return res;
		},
		getHeader(name) {
			if (name.toLowerCase() === "set-cookie") return setCookieHeaders.length > 0 ? setCookieHeaders : void 0;
			return resHeaders[name.toLowerCase()];
		},
		end(data) {
			if (ended) return;
			ended = true;
			if (data !== void 0 && data !== null) resBody = data;
			const headers = new Headers();
			for (const [key, value] of Object.entries(resHeaders)) headers.set(key, String(value));
			for (const cookie of setCookieHeaders) headers.append("set-cookie", cookie);
			resolveResponse(new Response(resBody, {
				status: resStatusCode,
				headers
			}));
		},
		status(code) {
			resStatusCode = code;
			return res;
		},
		json(data) {
			resHeaders["content-type"] = "application/json";
			res.end(JSON.stringify(data));
		},
		send(data) {
			if (Buffer.isBuffer(data)) {
				if (!resHeaders["content-type"]) resHeaders["content-type"] = "application/octet-stream";
				resHeaders["content-length"] = String(data.length);
				res.end(new Uint8Array(data));
				return;
			}
			if (typeof data === "object" && data !== null) {
				resHeaders["content-type"] = "application/json";
				res.end(JSON.stringify(data));
				return;
			}
			if (!resHeaders["content-type"]) resHeaders["content-type"] = "text/plain";
			res.end(String(data));
		},
		redirect(statusOrUrl, url) {
			if (typeof statusOrUrl === "string") res.writeHead(307, { Location: statusOrUrl });
			else res.writeHead(statusOrUrl, { Location: url ?? "" });
			res.end();
		},
		getHeaders() {
			const headers = { ...resHeaders };
			if (setCookieHeaders.length > 0) headers["set-cookie"] = setCookieHeaders;
			return headers;
		}
	};
	return {
		req,
		res,
		responsePromise
	};
}
//#endregion
export { PagesBodyParseError as PagesApiBodyParseError, createPagesReqRes, parsePagesApiBody };

//# sourceMappingURL=pages-node-compat.js.map