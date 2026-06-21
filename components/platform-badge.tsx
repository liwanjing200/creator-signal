import { Badge } from "@/components/badge";
import { platformLabel } from "@/lib/format";
import type { Platform } from "@/lib/types";

export function PlatformBadge({ platform }: { platform: Platform }) {
  return <Badge tone={platform === "bilibili" ? "blue" : "red"}>{platformLabel[platform]}</Badge>;
}

