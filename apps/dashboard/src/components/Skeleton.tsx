export interface SkeletonProps {
  shape?: "line" | "row" | "block";
}

/** Placeholder sized like the final content (no layout shift); decorative, so `aria-hidden`. */
export function Skeleton({ shape = "line" }: SkeletonProps) {
  const modifier = shape === "line" ? "" : ` skeleton--${shape}`;
  return <span className={`skeleton${modifier}`} aria-hidden="true" />;
}
