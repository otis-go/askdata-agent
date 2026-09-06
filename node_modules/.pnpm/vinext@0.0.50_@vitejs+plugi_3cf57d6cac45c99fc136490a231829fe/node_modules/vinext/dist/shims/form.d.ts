import * as _$react from "react";
import { FormHTMLAttributes, useActionState } from "react";

//#region src/shims/form.d.ts
declare const Form: _$react.ForwardRefExoticComponent<{
  /** Target URL for GET forms, or server action for POST forms */action: string | ((formData: FormData) => void | Promise<void>); /** Replace instead of push in history (default: false) */
  replace?: boolean; /** Scroll to top after navigation (default: true) */
  scroll?: boolean;
} & FormHTMLAttributes<HTMLFormElement> & _$react.RefAttributes<HTMLFormElement>>;
//#endregion
export { Form as default, useActionState };
//# sourceMappingURL=form.d.ts.map