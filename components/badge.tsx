import type { ReactNode } from "react";

export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "green" | "red" | "amber" | "blue" | "purple"; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

