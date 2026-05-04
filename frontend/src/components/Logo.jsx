import React from "react";

export default function Logo({ size = 96, withText = true }) {
  return (
    <div className="flex flex-col items-center select-none">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 120 120"
        width={size}
        height={size}
        aria-label="Natural Medical Solutions monogram"
      >
        <defs>
          <linearGradient id="nmsLeaf" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#3a5a48" />
            <stop offset="100%" stopColor="#6b8e7a" />
          </linearGradient>
        </defs>
        {/* Outer frame */}
        <rect x="8" y="8" width="104" height="104" rx="2" fill="none" stroke="#c19a4b" strokeWidth="0.8" />
        {/* Leaf */}
        <path
          d="M60 22 C 44 38, 40 58, 60 86 C 80 58, 76 38, 60 22 Z"
          fill="url(#nmsLeaf)"
          opacity="0.92"
        />
        <path d="M60 28 L60 82" stroke="#f6f1e6" strokeWidth="1" opacity="0.85" />
        {/* Monogram letters */}
        <text
          x="60"
          y="62"
          textAnchor="middle"
          fontFamily="Cormorant Garamond, Georgia, serif"
          fontSize="26"
          fontWeight="600"
          fill="#f6f1e6"
          letterSpacing="2"
        >
          N
        </text>
      </svg>
      {withText && (
        <div className="mt-2 text-center">
          <div
            className="font-display text-[13px] tracking-[0.28em] uppercase"
            style={{ color: "#6b4a1c" }}
          >
            Natural Medical Solutions
          </div>
          <div
            className="text-[10px] tracking-[0.32em] uppercase mt-0.5"
            style={{ color: "#8a6a3c" }}
          >
            Wellness Center
          </div>
        </div>
      )}
    </div>
  );
}
