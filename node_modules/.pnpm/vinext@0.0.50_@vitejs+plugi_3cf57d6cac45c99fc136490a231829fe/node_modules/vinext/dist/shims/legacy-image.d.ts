import React from "react";

//#region src/shims/legacy-image.d.ts
type LegacyImageProps = {
  src: string | {
    src: string;
    width: number;
    height: number;
    blurDataURL?: string;
  };
  alt: string;
  width?: number | string;
  height?: number | string; /** Legacy layout mode */
  layout?: "fixed" | "intrinsic" | "responsive" | "fill"; /** CSS object-fit (used with layout="fill") */
  objectFit?: React.CSSProperties["objectFit"]; /** CSS object-position (used with layout="fill") */
  objectPosition?: string;
  priority?: boolean;
  quality?: number;
  placeholder?: "blur" | "empty";
  blurDataURL?: string;
  loader?: (params: {
    src: string;
    width: number;
    quality?: number;
  }) => string;
  sizes?: string;
  className?: string;
  style?: React.CSSProperties;
  onLoad?: React.ReactEventHandler<HTMLImageElement>;
  onLoadingComplete?: (result: {
    naturalWidth: number;
    naturalHeight: number;
  }) => void;
  onError?: React.ReactEventHandler<HTMLImageElement>;
  loading?: "lazy" | "eager";
  unoptimized?: boolean;
  id?: string;
};
declare const LegacyImage: React.ForwardRefExoticComponent<LegacyImageProps & React.RefAttributes<HTMLImageElement>>;
//#endregion
export { LegacyImage as default };
//# sourceMappingURL=legacy-image.d.ts.map