// The Turnstone mark, a hang tag. Its outline still reads at 16 px, so the favicon uses the same drawing.
export function HangTag({ size = 30 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
      className="flex-none"
    >
      <path
        d="M11 3.5h10l5.5 5.5v20H5.5V9zM13.9 9.5a2.1 2.1 0 1 0 4.2 0a2.1 2.1 0 1 0 -4.2 0z"
        fill="#e2bf74"
        fillRule="evenodd"
        stroke="#3b2f1d"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path
        d="M12.3 9.5a3.7 3.7 0 1 0 7.4 0a3.7 3.7 0 1 0 -7.4 0zM13.9 9.5a2.1 2.1 0 1 0 4.2 0a2.1 2.1 0 1 0 -4.2 0z"
        fill="#b98c3c"
        fillRule="evenodd"
      />
      <path
        d="M16 9.5C17.5 4.5 21.5 1.6 28 1.4"
        fill="none"
        stroke="#3b2f1d"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  )
}
