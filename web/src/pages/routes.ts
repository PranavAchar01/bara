// Pages as URLs: / is the landing, /library the Library (finished builds and drafts; /drafts too), /build the Build page and /build/<id> one
// build on it. The store's screen stays the source of truth (the client moves it when a build
// starts or opens); this keeps the address bar in step with it both ways, so Back works and a
// /build/<id> link opens that build.
import { useEffect } from "react";
import { useApp } from "../state/store";
import { openLibraryBuild, openSaved } from "../net/client";
import { loadEntry } from "../library/library";

type Screen = "home" | "drafts" | "workspace";

export interface Route {
  screen: Screen;
  buildId: string | null;
}

const ID = /^[A-Za-z0-9_-]{1,64}$/;

export function parsePath(path: string): Route {
  const p = path.replace(/\/+$/, "") || "/";
  if (p === "/library" || p === "/drafts") return { screen: "drafts", buildId: null };
  const m = /^\/build(?:\/([^/]+))?$/.exec(p);
  if (m) {
    const id = m[1] ? decodeURIComponent(m[1]) : null;
    return { screen: "workspace", buildId: id && ID.test(id) ? id : null };
  }
  return { screen: "home", buildId: null };
}

export function pathFor(screen: Screen, buildId: string | null): string {
  if (screen === "drafts") return "/library";
  if (screen === "workspace") return buildId ? `/build/${encodeURIComponent(buildId)}` : "/build";
  return "/";
}

/** Shows the build a /build/<id> address names: this browser's copy first, else the engine's library. */
async function openById(id: string): Promise<void> {
  if (useApp.getState().build?.build_id === id) return;
  const local = await loadEntry(id).catch(() => null);
  if (local) openSaved(local);
  else await openLibraryBuild(id);
}

function apply(route: Route): void {
  const s = useApp.getState();
  if (route.screen === "workspace" && route.buildId && s.build?.build_id !== route.buildId) {
    void openById(route.buildId);
    return;
  }
  if (s.screen !== route.screen) useApp.setState({ screen: route.screen });
}

export function useRouteSync(): void {
  useEffect(() => {
    // the first address wins over a restored canvas, once the restore has had its turn
    const first = parsePath(window.location.pathname);
    let settled = false;
    const settle = () => {
      if (settled) return;
      settled = true;
      apply(first);
      write(false);
    };
    const write = (push: boolean) => {
      if (!settled) return;
      const s = useApp.getState();
      const want = pathFor(s.screen, s.screen === "workspace" ? (s.build?.build_id ?? null) : null);
      if (want === window.location.pathname) return;
      if (push) window.history.pushState(null, "", want + window.location.search);
      else window.history.replaceState(null, "", want + window.location.search);
    };
    const t = window.setTimeout(settle, 400);
    const unsub = useApp.subscribe((s, prev) => {
      if (!settled) return;
      // a new page is a history entry; the same page gaining its build id is not
      if (s.screen !== prev.screen) write(true);
      else if (s.build?.build_id !== prev.build?.build_id) write(s.screen === "workspace" && !!prev.build);
    });
    const onPop = () => apply(parsePath(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => {
      window.clearTimeout(t);
      unsub();
      window.removeEventListener("popstate", onPop);
    };
  }, []);
}
