import React from "react";

/**
 * Natural Medical Solutions logo.
 * The image already contains the full brand mark + wordmark, so `withText` is
 * kept only for legacy callsites (it has no visual effect — the wordmark is
 * baked into the image itself).
 */
export default function Logo({ size = 96, withText = true }) {
  return (
    <div className="select-none inline-flex items-center justify-center">
      <img
        src="/nms-logo.png"
        alt="Natural Medical Solutions"
        width={size}
        height={size}
        loading="eager"
        decoding="async"
        style={{ height: size, width: "auto", display: "block" }}
      />
    </div>
  );
}
