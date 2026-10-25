// One fetch per part id, shared by every view that needs a part's card (inspector, viewport, project links).
// Kept apart from the inspector UI so light screens can use it without pulling in the 3D code.
import { getRest } from "./client";
import { paths } from "./rest";
import type { Part } from "../spec/types";

const partCache = new Map<string, Promise<Part | null>>();

export function fetchPart(partId: string): Promise<Part | null> {
  let p = partCache.get(partId);
  if (!p) {
    p = getRest()
      .get<{ part: Part }>(paths.part(partId))
      .then((r) => (r.ok ? ((r.body as { part?: Part }).part ?? null) : null));
    partCache.set(partId, p);
  }
  return p;
}
