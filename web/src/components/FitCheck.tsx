import { useState } from "react";
import { useApp } from "../state/store";
import { applyEdit, getRest, startBuild } from "../net/client";
import { serverUrl } from "../net/mode";
import type { EditOp } from "../spec/types";
import { Icon } from "../ui/common";

type Step = { tool?: string; decide?: string; status?: string; where?: string; ms?: number; why?: string; reason?: string; [k: string]: unknown };
type FitAction = { kind: "build" | "prompt" | "edit" | "retake" | "none"; label: string; prompt?: string; ops?: EditOp[]; needs_approval: boolean };
type FitResult = {
  measurement: {
    status: string;
    opencv: string;
    where?: string;
    object: { width_mm: number; depth_mm: number; kind: string } | null;
  };
  annotated_jpg_b64: string;
  steps: Step[];
  fit?: { case_mm: number[]; space_mm: number[]; footprint_fits: boolean; spare_mm: number; height_fits: boolean };
  action: FitAction;
  message: string;
};

/** Shrink the photo in the browser before it leaves: 1600 px JPEG, which also drops EXIF and GPS. */
async function shrink(file: File): Promise<string> {
  const bmp = await createImageBitmap(file);
  const scale = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * scale);
  c.height = Math.round(bmp.height * scale);
  c.getContext("2d")?.drawImage(bmp, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.9).split(",", 2)[1] ?? "";
}

function stepLine(s: Step): string {
  if (s.tool === "measure") return `measure${s.why ? " again" : ""} (${s.where === "aws-lambda" ? "AWS Lambda" : "local"}${s.ms ? `, ${Math.round(s.ms)} ms` : ""}): ${s.status}`;
  if (s.tool === "fit_check") return `fit check: case ${(s.case_mm as number[]).slice(0, 2).map((v) => v.toFixed(0)).join(" x ")} vs space ${(s.space_mm as number[]).join(" x ")} mm`;
  if (s.decide) return `decide: ${s.decide.replace(/_/g, " ")}${s.reason ? ` (${String(s.reason).replace(/_/g, " ")})` : ""}`;
  return JSON.stringify(s);
}

/** Fit check: one photo of a real space or object next to a printed marker; OpenCV measures it and
 * the agent proposes the next step for the build (size it, shrink it, or retake the photo). */
export function FitCheck() {
  const build = useApp((s) => s.build);
  const enc = build?.enclosures.find((e) => e.kind !== "none" && e.outer_size_mm);
  const [mode, setMode] = useState<"fit_inside" | "match">("fit_inside");
  const [markerMm, setMarkerMm] = useState(40);
  const [heightMm, setHeightMm] = useState("");
  const [device, setDevice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FitResult | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [last, setLast] = useState<string | null>(null);

  const run = async (b64: string) => {
    setBusy(true);
    setError(null);
    const res = await getRest().request<FitResult>("POST", "/v1/vision/fit", {
      image_b64: b64,
      mode,
      marker_mm: markerMm,
      height_limit_mm: heightMm ? Number(heightMm) : undefined,
      device,
      enclosure: enc ? { enclosure_id: enc.enclosure_id, outer_size_mm: enc.outer_size_mm } : undefined,
    });
    setBusy(false);
    if (res.ok) setResult(res.body);
    else setError(res.error.message);
  };

  const onFile = async (f: File | undefined) => {
    if (!f) return;
    const b64 = await shrink(f);
    setPreview(`data:image/jpeg;base64,${b64}`);
    setLast(b64);
    setResult(null);
    await run(b64);
  };

  const act = (a: FitAction) => {
    if (a.kind === "prompt" && a.prompt && build) {
      // a shrink is a rebuild of this same device on this canvas, with the measured limit added
      startBuild(`${build.prompt.trim().replace(/\.$/, "")}. ${a.prompt}`);
    } else if ((a.kind === "build" || a.kind === "prompt") && a.prompt) {
      window.dispatchEvent(new CustomEvent("bara:prompt", { detail: a.prompt }));
    } else if (a.kind === "edit" && a.ops) {
      applyEdit(a.ops, a.label);
    }
  };

  const obj = result?.measurement.object;
  return (
    <aside className="side-overlay" aria-label="Fit check">
      <header className="side-h">
        <div className="side-title">
          <h2>Fit check</h2>
          <span className="muted small mono">OpenCV {result?.measurement.opencv ?? "5"} on AWS</span>
        </div>
        <button type="button" className="btn ghost sm icon" aria-label="Close" onClick={() => useApp.setState({ overlay: null })}>
          <Icon name="x" />
        </button>
      </header>
      <div className="side-b">
        <p className="muted small">
          Lay the printed marker flat next to the space or object and take one photo from above.{" "}
          <a href={serverUrl(`/v1/vision/marker.png?mm=${markerMm}`)} target="_blank" rel="noreferrer">
            Print the marker
          </a>
        </p>
        <div className="fit-modes" role="radiogroup" aria-label="What the photo shows" style={{ display: "flex", gap: 6, margin: "8px 0" }}>
          <button type="button" role="radio" aria-checked={mode === "fit_inside"} className={`btn sm ${mode === "fit_inside" ? "on" : ""}`} onClick={() => setMode("fit_inside")}>
            A space it must fit
          </button>
          <button type="button" role="radio" aria-checked={mode === "match"} className={`btn sm ${mode === "match" ? "on" : ""}`} onClick={() => setMode("match")}>
            An outline to match
          </button>
        </div>
        <label className="slider">
          <span>Marker</span>
          <input type="number" min={15} max={150} value={markerMm} onChange={(e) => setMarkerMm(Number(e.target.value) || 40)} />
          <span className="mono small">mm</span>
        </label>
        <label className="slider">
          <span>Max height</span>
          <input type="number" min={3} max={500} placeholder="any" value={heightMm} onChange={(e) => setHeightMm(e.target.value)} />
          <span className="mono small">mm</span>
        </label>
        {!enc && (
          <label className="slider">
            <span>Device</span>
            <input type="text" placeholder="a macro pad with four keys" value={device} onChange={(e) => setDevice(e.target.value)} />
          </label>
        )}
        <label className="btn" style={{ display: "block", textAlign: "center", margin: "10px 0" }}>
          {busy ? "Measuring..." : preview ? "Use another photo" : "Take or choose a photo"}
          <input type="file" accept="image/*" capture="environment" hidden disabled={busy} onChange={(e) => void onFile(e.target.files?.[0])} />
        </label>
        {error && <p className="small" role="alert">{error}</p>}
        {result && (
          <div className="fit-result" aria-live="polite">
            {result.annotated_jpg_b64 ? (
              <img src={`data:image/jpeg;base64,${result.annotated_jpg_b64}`} alt="Top-down view with the measured outline" style={{ width: "100%", borderRadius: 8 }} />
            ) : (
              preview && <img src={preview} alt="Your photo" style={{ width: "100%", borderRadius: 8, opacity: 0.6 }} />
            )}
            {obj && (
              <p className="mono">
                {obj.width_mm.toFixed(1)} x {obj.depth_mm.toFixed(1)} mm, {obj.kind}
              </p>
            )}
            <p>{result.message}</p>
            <ol className="muted small mono" style={{ paddingLeft: 18 }}>
              {result.steps.map((s, i) => (
                <li key={i}>{stepLine(s)}</li>
              ))}
            </ol>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {result.action.needs_approval && (
                <button type="button" className="btn primary sm" onClick={() => act(result.action)}>
                  {result.action.label}
                </button>
              )}
              {enc && last && (
                <button type="button" className="btn sm" disabled={busy} onClick={() => void run(last)}>
                  Check again
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
