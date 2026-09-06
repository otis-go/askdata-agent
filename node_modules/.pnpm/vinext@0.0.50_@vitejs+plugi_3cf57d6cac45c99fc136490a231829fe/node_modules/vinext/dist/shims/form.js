"use client";
import { isDangerousScheme } from "./url-safety.js";
import { toSameOriginPath } from "./url-utils.js";
import { navigateClientSide } from "./navigation.js";
import { forwardRef, useActionState } from "react";
import { jsx } from "react/jsx-runtime";
//#region src/shims/form.tsx
/**
* next/form shim
*
* Progressive enhancement form component. In Next.js, this replaces
* the standard <form> element with one that intercepts submissions
* and performs client-side navigation for GET forms (search forms).
*
* For POST forms with server actions, it delegates to React's built-in
* form action handling.
*
* Usage:
*   import Form from 'next/form';
*   <Form action="/search">
*     <input name="q" />
*     <button type="submit">Search</button>
*   </Form>
*/
const SUPPORTED_FORM_ENCTYPE = "application/x-www-form-urlencoded";
const SUPPORTED_FORM_METHOD = "GET";
const SUPPORTED_FORM_TARGET = "_self";
function isSafeAction(action) {
	if (isDangerousScheme(action)) return false;
	if (action.startsWith("//")) return false;
	if (/^https?:\/\//i.test(action)) {
		if (typeof window !== "undefined") try {
			return new URL(action).origin === window.location.origin;
		} catch {
			return false;
		}
		return false;
	}
	return true;
}
function getSubmitter(nativeEvent) {
	const submitter = nativeEvent && typeof nativeEvent === "object" && "submitter" in nativeEvent && nativeEvent.submitter instanceof Element ? nativeEvent.submitter : null;
	if (submitter instanceof HTMLButtonElement || submitter instanceof HTMLInputElement) return submitter;
	return null;
}
function getEffectiveMethod(submitter, formMethod) {
	return (submitter?.getAttribute("formmethod") ?? formMethod ?? "GET").toUpperCase();
}
function getEffectiveAction(submitter, formAction) {
	return submitter?.getAttribute("formaction") ?? formAction;
}
function checkFormActionUrl(action, source) {
	const aPropName = source === "action" ? "an `action`" : "a `formAction`";
	let testUrl;
	try {
		testUrl = new URL(action, "http://n");
	} catch {
		console.error(`<Form> received ${aPropName} that cannot be parsed as a URL: "${action}".`);
		return;
	}
	if (testUrl.searchParams.size) console.warn(`<Form> received ${aPropName} that contains search params: "${action}". This is not supported, and they will be ignored. If you need to pass in additional search params, use an \`<input type="hidden" />\` instead.`);
}
function hasUnsupportedSubmitterAttributes(submitter) {
	const formEncType = submitter.getAttribute("formenctype");
	if (formEncType !== null && formEncType !== SUPPORTED_FORM_ENCTYPE) {
		console.error(`<Form>'s \`encType\` was set to an unsupported value via \`formEncType="${formEncType}"\`. This will disable <Form>'s navigation functionality. If you need this, use a native <form> element instead.`);
		return true;
	}
	const formMethod = submitter.getAttribute("formmethod");
	if (formMethod !== null && formMethod.toUpperCase() !== SUPPORTED_FORM_METHOD) {
		console.error(`<Form>'s \`method\` was set to an unsupported value via \`formMethod="${formMethod}"\`. This will disable <Form>'s navigation functionality. If you need this, use a native <form> element instead.`);
		return true;
	}
	const formTarget = submitter.getAttribute("formtarget");
	if (formTarget !== null && formTarget !== SUPPORTED_FORM_TARGET) {
		console.error(`<Form>'s \`target\` was set to an unsupported value via \`formTarget="${formTarget}"\`. This will disable <Form>'s navigation functionality. If you need this, use a native <form> element instead.`);
		return true;
	}
	return false;
}
function createFormSubmitDestinationUrl(action, form, submitter) {
	const targetUrl = new URL(action, window.location.href);
	if (targetUrl.searchParams.size) targetUrl.search = "";
	const formData = buildFormData(form, submitter);
	for (const [name, value] of formData) targetUrl.searchParams.append(name, typeof value === "string" ? value : value.name);
	return toSameOriginPath(targetUrl.href) ?? targetUrl.href;
}
function buildFormData(form, submitter) {
	if (!submitter) return new FormData(form);
	try {
		return new FormData(form, submitter);
	} catch {
		const formData = new FormData(form);
		if (!submitter.disabled && submitter.name) formData.append(submitter.name, submitter.value);
		return formData;
	}
}
const Form = forwardRef(function Form(props, ref) {
	const { action, replace = false, scroll = true, onSubmit, ...rest } = props;
	if (typeof action === "function") return /* @__PURE__ */ jsx("form", {
		ref,
		action,
		onSubmit,
		...rest
	});
	if (process.env.NODE_ENV !== "production") checkFormActionUrl(action, "action");
	if (!isSafeAction(action)) {
		if (process.env.NODE_ENV !== "production") console.warn(`<Form> blocked unsafe action: ${action}`);
		return /* @__PURE__ */ jsx("form", {
			ref,
			onSubmit,
			...rest
		});
	}
	async function handleSubmit(e) {
		if (onSubmit) {
			onSubmit(e);
			if (e.defaultPrevented) return;
		}
		const submitter = getSubmitter(e.nativeEvent);
		if (submitter && hasUnsupportedSubmitterAttributes(submitter)) return;
		if (getEffectiveMethod(submitter, rest.method) !== "GET") return;
		const effectiveAction = getEffectiveAction(submitter, action);
		if (process.env.NODE_ENV !== "production" && submitter?.getAttribute("formaction") !== null) checkFormActionUrl(effectiveAction, "formAction");
		if (!isSafeAction(effectiveAction)) {
			if (process.env.NODE_ENV !== "production") console.warn(`<Form> blocked unsafe action: ${effectiveAction}`);
			e.preventDefault();
			return;
		}
		e.preventDefault();
		const url = createFormSubmitDestinationUrl(effectiveAction, e.currentTarget, submitter);
		if (typeof window.__VINEXT_RSC_NAVIGATE__ === "function") await navigateClientSide(url, replace ? "replace" : "push", scroll);
		else {
			if (replace) window.history.replaceState({}, "", url);
			else window.history.pushState({}, "", url);
			window.dispatchEvent(new PopStateEvent("popstate"));
		}
		if (typeof window.__VINEXT_RSC_NAVIGATE__ !== "function" && scroll) window.scrollTo(0, 0);
	}
	return /* @__PURE__ */ jsx("form", {
		ref,
		action,
		onSubmit: (event) => {
			handleSubmit(event);
		},
		...rest
	});
});
//#endregion
export { Form as default, useActionState };

//# sourceMappingURL=form.js.map