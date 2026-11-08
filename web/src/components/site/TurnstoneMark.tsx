// The Turnstone mark: a turnstone tipping over a stone, as the app turns over donations to find what's worth selling.
// It draws in the text color, with the eye cut out in the background color, so it sits on the dark band in the header.
// public/favicon.svg is the same drawing with its colors written in.
export function TurnstoneMark({ size = 30 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
      className="flex-none"
    >
      <path d="M4.2 12.4 0.8 10.4 4.6 16.2z" fill="currentColor" />
      <ellipse
        cx="11"
        cy="15.6"
        rx="7.6"
        ry="5.4"
        transform="rotate(18 11 15.6)"
        fill="currentColor"
      />
      <circle cx="17" cy="19.2" r="3.9" fill="currentColor" />
      <path d="M19.6 17.6 24.6 22.3 19.2 22z" fill="currentColor" />
      <circle cx="17.9" cy="18.1" r="0.9" fill="var(--background)" />
      <path
        d="M9 21 8.5 25.5M12.6 21.5 12.9 25.5"
        stroke="#d0703a"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <ellipse
        cx="27"
        cy="21.6"
        rx="4.4"
        ry="3"
        transform="rotate(-32 27 21.6)"
        fill="currentColor"
        opacity=".4"
      />
    </svg>
  )
}
