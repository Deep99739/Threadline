type BrandMarkProps = {
  className?: string;
};

export function BrandMark({ className }: BrandMarkProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      viewBox="0 0 96 64"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M4 32H28V14H48V27"
        stroke="currentColor"
        strokeLinecap="square"
        strokeLinejoin="miter"
        strokeWidth="8"
      />
      <path
        d="M48 37V50H68V32H92"
        stroke="currentColor"
        strokeLinecap="square"
        strokeLinejoin="miter"
        strokeWidth="8"
      />
      <rect fill="var(--accent, #793f31)" height="14" width="14" x="41" y="25" />
    </svg>
  );
}
