// A tab drawn as a pill, with the open one filled green, for Radix tabs. Only a tab that isn't
// open darkens on hover, so the open one keeps its colors.
export const pillTab =
  'cursor-pointer rounded-full bg-muted px-3.5 py-1.5 text-left text-[0.9375rem] leading-[1.3] font-semibold text-foreground transition-colors data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=inactive]:hover:bg-[color-mix(in_oklch,var(--muted),var(--foreground)_8%)]'
