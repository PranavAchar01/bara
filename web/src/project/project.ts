// The project around the open device: its scene (this canvas and its companions), the links
// between them, and their ports. Links live here, not in any one build, and are kept in local
// storage with the open canvases so a reload brings the project back. A link to a closed
// canvas is dropped.
import { useEffect, useMemo, useState } from "react";
import { create } from "zustand";
import { useShallow } from "zustand/react/shallow";
import { useApp, type AppState } from "../state/store";
import { canvasLabel, canvasState } from "../state/canvases";
import { fetchPart } from "../components/Overlays";
import type { Build, Part } from "../spec/types";
import { portsOf, type DevicePort, type ProjectLink } from "./links";

const KEY = "bara.project.links";

function load(): ProjectLink[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "[]") as unknown;
    return Array.isArray(raw) ? (raw as ProjectLink[]).filter((l) => l && l.a && l.b && l.link_id) : [];
  } catch {
    return [];
  }
}

function save(links: ProjectLink[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(links));
  } catch {
    // storage blocked: links still work for this page
  }
}

export const useProject = create<{ links: ProjectLink[]; open: boolean }>(() => ({ links: load(), open: false }));

export function addLink(l: ProjectLink): void {
  useProject.setState((s) => {
    const links = [...s.links, l];
    save(links);
    return { links };
  });
}

export function removeLink(id: string): void {
  useProject.setState((s) => {
    const links = s.links.filter((l) => l.link_id !== id);
    save(links);
    return { links };
  });
}

export function setProjectOpen(open: boolean): void {
  useProject.setState({ open });
}

/** Drop links whose device canvas was closed. */
export function startLinkPruning(): () => void {
  return useApp.subscribe((s) => {
    const live = new Set(s.canvases.map((c) => c.id));
    const { links } = useProject.getState();
    const kept = links.filter((l) => live.has(l.a.canvasId) && live.has(l.b.canvasId));
    if (kept.length !== links.length) {
      save(kept);
      useProject.setState({ links: kept });
    }
  });
}

export interface ProjectDevice {
  canvasId: string;
  name: string;
  build: Build | null;
  active: boolean;
}

/** The devices in the open canvas's scene, in tab order. */
export function projectDevices(s: AppState): ProjectDevice[] {
  const scene = new Set([s.activeCanvas, ...s.companions]);
  return s.canvases
    .filter((m) => scene.has(m.id))
    .map((m) => {
      const c = canvasState(s, m.id);
      return { canvasId: m.id, name: canvasLabel(m, c), build: c?.build ?? null, active: m.id === s.activeCanvas };
    });
}

export function useProjectDevices(): ProjectDevice[] {
  const key = useApp(
    useShallow((s) => projectDevices(s).map((d) => `${d.canvasId}:${d.name}:${d.build?.build_id ?? ""}:${d.build?.revision ?? 0}:${d.build?.parts.length ?? 0}:${d.active ? 1 : 0}`)),
  );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(() => projectDevices(useApp.getState()), [key.join("|")]);
}

/** Every outward port of every device in the project; catalog parts are fetched once each. */
export function useProjectPorts(devices: ProjectDevice[]): DevicePort[] {
  const ids = useMemo(() => [...new Set(devices.flatMap((d) => d.build?.parts.map((p) => p.part_id) ?? []))].sort(), [devices]);
  const [parts, setParts] = useState<Record<string, Part | null>>({});
  useEffect(() => {
    let live = true;
    const missing = ids.filter((id) => !(id in parts));
    if (!missing.length) return;
    void Promise.all(missing.map(async (id) => [id, await fetchPart(id).catch(() => null)] as const)).then((got) => {
      if (live) setParts((p) => ({ ...p, ...Object.fromEntries(got) }));
    });
    return () => {
      live = false;
    };
  }, [ids, parts]);
  return useMemo(() => devices.flatMap((d) => portsOf(d.canvasId, d.build, parts)), [devices, parts]);
}
