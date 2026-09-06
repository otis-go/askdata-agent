import React from "react";

//#region src/shims/error.d.ts
type ErrorProps = {
  statusCode: number;
  title?: string;
  withDarkMode?: boolean;
};
declare function ErrorComponent({
  statusCode,
  title
}: ErrorProps): React.ReactElement;
//#endregion
export { ErrorComponent as default };
//# sourceMappingURL=error.d.ts.map