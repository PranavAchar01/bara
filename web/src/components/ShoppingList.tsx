// Shopping list: the build's bill of materials as a table you can buy from (GET export
// ?format=bom_json): part, maker, MPN, quantity, prices, buy links, the printed case with its
// STL/3MF files, and the known total. Download CSV hits format=bom_csv.
import { useEffect, useState } from "react";
import { useApp } from "../state/store";
import { getRest } from "../net/client";
import { paths } from "../net/rest";
import { serverUrl } from "../net/mode";
import { Icon } from "../ui/common";

interface BomRow {
  part_id: string;
  kind: string;
  name: string;
  manufacturer: string;
  mpn: string;
  quantity: number;
  unit_price_usd: number | null;
  line_total_usd: number | null;
  lcsc_url: string;
  digikey_url: string;
  mouser_url: string;
  file_url: string;
}
interface CaseFiles {
  enclosure_id: string;
  stl: string;
  "3mf": string;
}
interface Bom {
  rows: BomRow[];
  case_files: CaseFiles[];
  totals: { lines: number; priced_lines: number; known_total_usd: number | null };
}

/** Only web links leave the page; anything else from the engine is dropped. */
const web = (u: string | undefined) => (u && /^https?:\/\//i.test(u) ? u : "");
/** Engine files are served relative to it. */
const file = (u: string | undefined) => (u && u.startsWith("/v1/") ? serverUrl(u) : web(u));
const usd = (n: number | null) => (n === null || n === undefined ? "" : `$${n.toFixed(n < 1 ? 3 : 2)}`);

/** compact: an icon button, for the narrow panel toolbar beside Export. */
export function ShoppingListButton(props: { compact?: boolean }) {
  const build = useApp((s) => s.build);
  const [open, setOpen] = useState(false);
  const ready = build?.status === "done";
  return (
    <>
      <button
        type="button"
        className={`btn sm ${props.compact ? "ghost icon" : ""}`}
        disabled={!ready}
        onClick={() => setOpen(true)}
        aria-label="Shopping list"
        title={ready ? "Shopping list" : "The shopping list is ready when the build is done"}
      >
        <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M1.5 2h2l1.6 8h7.4l1.5-5.5H4.3" />
          <circle cx="6.2" cy="13" r="1" />
          <circle cx="11.8" cy="13" r="1" />
        </svg>
        {!props.compact && " Shopping list"}
      </button>
      {open && build && <ShoppingList buildId={build.build_id} onClose={() => setOpen(false)} />}
    </>
  );
}

function ShoppingList(props: { buildId: string; onClose: () => void }) {
  const { buildId, onClose } = props;
  const [bom, setBom] = useState<Bom | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void getRest()
      .get<{ bom: Bom }>(paths.export(buildId, "bom_json"))
      .then((res) => {
        if (!live) return;
        if (res.ok && res.body.bom) setBom(res.body.bom);
        else setError(res.ok ? "The engine sent no list." : res.error.message);
      });
    return () => {
      live = false;
    };
  }, [buildId]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);
  const caseFiles = new Map((bom?.case_files ?? []).map((c) => [c.enclosure_id, c]));
  return (
    <div className="bd-scrim" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="bd-card sl-card" role="dialog" aria-modal="true" aria-labelledby="sl-h">
        <button type="button" className="btn ghost sm icon bd-close" aria-label="Close" onClick={onClose}>
          <Icon name="x" />
        </button>
        <h2 id="sl-h">Shopping list</h2>
        <p className="bd-sub">
          {bom
            ? `${bom.totals.lines} lines${bom.totals.known_total_usd !== null ? `, about ${usd(bom.totals.known_total_usd)} for the ${bom.totals.priced_lines} with a stated price` : ""}. Prices are what the catalog states; check the seller before buying.`
            : error
              ? error
              : "Reading the parts…"}
        </p>
        {bom && (
          <div className="sl-scroll">
            <table className="sl-table">
              <thead>
                <tr>
                  <th>Part</th>
                  <th>Maker</th>
                  <th>MPN</th>
                  <th className="num">Qty</th>
                  <th className="num">Unit</th>
                  <th className="num">Line</th>
                  <th>Buy or print</th>
                </tr>
              </thead>
              <tbody>
                {bom.rows.map((r) => {
                  const cf = caseFiles.get(r.part_id);
                  const buy = [
                    ["LCSC", web(r.lcsc_url)],
                    ["Digi-Key", web(r.digikey_url)],
                    ["Mouser", web(r.mouser_url)],
                  ].filter(([, u]) => u);
                  const files =
                    r.kind === "3d_print"
                      ? [
                          ["STL", file(cf?.stl ?? r.file_url)],
                          ["3MF", file(cf?.["3mf"])],
                        ].filter(([, u]) => u)
                      : r.kind === "pcb"
                        ? [["KiCad", file(r.file_url)]].filter(([, u]) => u)
                        : [];
                  return (
                    <tr key={r.part_id}>
                      <td>{r.name}</td>
                      <td>{r.manufacturer}</td>
                      <td className="mono">{r.mpn}</td>
                      <td className="num">{r.quantity}</td>
                      <td className="num">{usd(r.unit_price_usd)}</td>
                      <td className="num">{usd(r.line_total_usd)}</td>
                      <td className="sl-links">
                        {[...buy, ...files].map(([label, u]) => (
                          <a key={label} href={u} target="_blank" rel="noopener noreferrer">
                            {label}
                          </a>
                        ))}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              {bom.totals.known_total_usd !== null && (
                <tfoot>
                  <tr>
                    <td colSpan={5}>Known total</td>
                    <td className="num">{usd(bom.totals.known_total_usd)}</td>
                    <td />
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        )}
        <p className="bd-foot sl-foot">
          <a className="btn primary sm" href={serverUrl(paths.export(buildId, "bom_csv"))} download>
            Download CSV
          </a>
        </p>
      </div>
    </div>
  );
}
