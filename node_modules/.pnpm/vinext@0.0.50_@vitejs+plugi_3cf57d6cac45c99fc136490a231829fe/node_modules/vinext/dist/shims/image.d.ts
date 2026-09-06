import React from "react";

//#region src/shims/image.d.ts
type StaticImageData = {
  src: string;
  height: number;
  width: number;
  blurDataURL?: string;
};
type ImageProps = {
  src: string | StaticImageData;
  alt: string;
  width?: number;
  height?: number;
  fill?: boolean;
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
  onLoad?: React.ReactEventHandler<HTMLImageElement>; /** @deprecated Use onLoad instead. Still supported for migration compat. */
  onLoadingComplete?: (img: HTMLImageElement) => void;
  onError?: React.ReactEventHandler<HTMLImageElement>;
  onClick?: React.MouseEventHandler<HTMLImageElement>;
  id?: string;
  unoptimized?: boolean;
  overrideSrc?: string;
  loading?: "lazy" | "eager";
};
/**
 * Build a `/_vinext/image` optimization URL.
 *
 * In production (Cloudflare Workers), the worker intercepts this path and uses
 * the Images binding to resize/transcode on the fly. In dev, the Vite dev
 * server handles it as a passthrough (serves the original file).
 */
declare function imageOptimizationUrl(src: string, width: number, quality?: number): string;
declare const Image: React.ForwardRefExoticComponent<ImageProps & React.RefAttributes<HTMLImageElement>>;
/**
 * getImageProps — for advanced use cases (picture elements, background images).
 * Returns the props that would be passed to the underlying <img> element.
 */
declare function getImageProps(props: ImageProps): {
  props: React.ImgHTMLAttributes<HTMLImageElement>;
};
//#endregion
export { StaticImageData, Image as default, getImageProps, imageOptimizationUrl };
//# sourceMappingURL=image.d.ts.map