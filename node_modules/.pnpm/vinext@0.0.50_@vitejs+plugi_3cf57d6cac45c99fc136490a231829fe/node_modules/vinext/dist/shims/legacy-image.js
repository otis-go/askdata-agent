import Image from "./image.js";
import { forwardRef } from "react";
import { jsx } from "react/jsx-runtime";
//#region src/shims/legacy-image.tsx
/**
* next/legacy/image shim
*
* Provides the pre-Next.js 13 Image component API with layout prop.
* Translates legacy props (layout, objectFit, objectPosition) to the
* modern Image component's fill/style props.
*
* This module is used by apps that ran the `next-image-to-legacy-image`
* codemod when upgrading from Next.js 12.
*/
const LegacyImage = forwardRef(function LegacyImage(props, ref) {
	const { layout = "intrinsic", objectFit, objectPosition, onLoadingComplete, onLoad, width, height, style, ...rest } = props;
	const modernStyle = { ...style };
	if (objectFit) modernStyle.objectFit = objectFit;
	if (objectPosition) modernStyle.objectPosition = objectPosition;
	const handleLoad = onLoadingComplete ? (e) => {
		const img = e.currentTarget;
		onLoadingComplete({
			naturalWidth: img.naturalWidth,
			naturalHeight: img.naturalHeight
		});
		onLoad?.(e);
	} : onLoad;
	if (layout === "fill") return /* @__PURE__ */ jsx(Image, {
		ref,
		fill: true,
		style: modernStyle,
		onLoad: handleLoad,
		...rest
	});
	if (layout === "responsive") {
		modernStyle.width = "100%";
		modernStyle.height = "auto";
	}
	return /* @__PURE__ */ jsx(Image, {
		ref,
		width: typeof width === "string" ? parseInt(width, 10) : width,
		height: typeof height === "string" ? parseInt(height, 10) : height,
		style: modernStyle,
		onLoad: handleLoad,
		...rest
	});
});
//#endregion
export { LegacyImage as default };

//# sourceMappingURL=legacy-image.js.map