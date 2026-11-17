import { useState } from "react";
import axios from "axios";
import "./styles/MAOLogin.css";

const API = "http://localhost:8000/api";
const CATS = ["boar", "sow", "gilts", "piglets", "grower_fattener"] as const;

type Cat = (typeof CATS)[number];
type CatOrUnclassified = Cat | "unclassified";
const ALL: CatOrUnclassified[] = [...CATS, "unclassified"];

const LABELS: Record<CatOrUnclassified, string> = {
  boar: "Boar",
  sow: "Sow",
  gilts: "Gilts",
  piglets: "Piglets",
  grower_fattener: "Grower/Fattener",
  unclassified: "Not broken down",
};

// Movement types (same as the MAO staff module and the backend)
const IN_TYPES: [string, string][] = [
  ["birth", "Births"],
  ["purchase", "Purchased"],
  ["transfer_in", "Transferred in"],
];
const OUT_TYPES: [string, string][] = [
  ["sale", "Sold"],
  ["slaughter", "Slaughtered"],
  ["death", "Died"],
  ["transfer_out", "Transferred out"],
  ["depopulated", "Depopulated (ASF)"],
];
const MOVEMENT_LABEL: Record<string, string> = Object.fromEntries([...IN_TYPES, ...OUT_TYPES]);
const IS_IN = new Set(IN_TYPES.map(([t]) => t));

type Mode = "total" | "category";
// category null = the whole herd (total-only farmers) or animals "not broken down"
type Line = { movement_type: string; category: Cat | null; quantity: number };

type Pop = {
  total: number;
  has_breakdown: boolean;
  unclassified: number | null; // animals counted in the total but not assigned to a class
} & Record<Cat, number | null>;

type Me = { farmer_name: string; address: string; population: Pop };

const emptyCats = (): Record<Cat, string> => ({
  boar: "", sow: "", gilts: "", piglets: "", grower_fattener: "",
});

// Local date (toISOString would give the UTC date, which can be yesterday early in the morning)
const today = () => {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
};

const periodLabel = (type: string, end: string) => {
  const d = new Date(end + "T00:00:00");
  if (isNaN(d.getTime())) return end;
  return type === "quarterly"
    ? `Q${Math.floor(d.getMonth() / 3) + 1} ${d.getFullYear()}`
    : d.toLocaleDateString("en-PH", { month: "long", year: "numeric" });
};

function FarmerLivestock() {
  const [farmerId, setFarmerId] = useState("");
  const [token, setToken] = useState("");
  const [me, setMe] = useState<Me | null>(null);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  // Periodic report
  const [periodType, setPeriodType] = useState<"monthly" | "quarterly">("monthly");
  const [periodEnd, setPeriodEnd] = useState(today());
  const [mode, setMode] = useState<Mode>("total"); // only used for a farmer's very first (starting) count
  const [totalCount, setTotalCount] = useState(""); // starting count only
  const [counts, setCounts] = useState<Record<Cat, string>>(emptyCats()); // starting count only
  const [lines, setLines] = useState<Line[]>([]);
  const [mvType, setMvType] = useState("");
  const [mvCat, setMvCat] = useState<CatOrUnclassified | "">("");
  const [mvQty, setMvQty] = useState("");
  const [remarks, setRemarks] = useState("");
  const [saving, setSaving] = useState(false);

  // "Update herd breakdown" panel
  const [showBreakdown, setShowBreakdown] = useState(false);
  const [draft, setDraft] = useState<Record<Cat, string>>(emptyCats());

  const auth = (t: string) => ({ headers: { Authorization: `Bearer ${t}` } });

  const login = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await axios.post(`${API}/farmer-login`, { farmer_id: Number(farmerId) });
      const info = await axios.get(`${API}/farmer/me`, auth(res.data.token));

      setToken(res.data.token);
      setMsg(null);
      alert(`Login successful. Welcome, ${info.data.farmer_name}!`); // popup first
      setMe(info.data); // form shows after OK
    } catch {
      setMsg({ type: "err", text: "Login failed: the farmer ID you entered is not valid." });
    }
  };

  const banner = msg && (
    <p role="alert" style={{ color: msg.type === "ok" ? "#04503c" : "#b91c1c", marginBottom: 12 }}>
      {msg.text}
    </p>
  );

  if (!me) {
    return (
      <div className="login-card">
        <h2 className="login-title">Farmer login</h2>
        {banner}
        <form onSubmit={login}>
          <div className="login-fields">
            <input placeholder="Farmer ID" value={farmerId}
                   onChange={(e) => setFarmerId(e.target.value)} required />
          </div>
          <button type="submit" className="login-primary">Login</button>
        </form>
      </div>
    );
  }

  const pop = me.population;

  // Animals counted in the total but not assigned to a class.
  // Total-only farmers: the whole total. By-class farmers: whatever the server reports.
  const unclassified = pop.has_breakdown ? pop.unclassified ?? 0 : pop.total;

  // ---------- How this farmer reports ----------
  // A farmer with a count on record keeps reporting the same way:
  //   by category if the herd is broken down, otherwise the total only.
  // Only a farmer with no count yet (starting count) chooses.
  const starting = pop.total === 0;
  const reportMode: Mode = starting ? mode : pop.has_breakdown ? "category" : "total";

  // ---------- Inventory on hand = opening + movements, per category or in total ----------
  const openingOf = (b: CatOrUnclassified) => (b === "unclassified" ? unclassified : pop[b] ?? 0);
  const bucketOf = (l: Line): CatOrUnclassified => l.category ?? "unclassified";
  const inOf = (b: CatOrUnclassified) =>
    lines.filter((l) => bucketOf(l) === b && IS_IN.has(l.movement_type)).reduce((s, l) => s + l.quantity, 0);
  const outOf = (b: CatOrUnclassified) =>
    lines.filter((l) => bucketOf(l) === b && !IS_IN.has(l.movement_type)).reduce((s, l) => s + l.quantity, 0);

  const onHand = Object.fromEntries(
    ALL.map((b) => [b, openingOf(b) + inOf(b) - outOf(b)])
  ) as Record<CatOrUnclassified, number>;

  const totalIn = lines.filter((l) => IS_IN.has(l.movement_type)).reduce((s, l) => s + l.quantity, 0);
  const totalOut = lines.filter((l) => !IS_IN.has(l.movement_type)).reduce((s, l) => s + l.quantity, 0);

  // Starting count: typed by the farmer. Otherwise: calculated.
  const typedCats = Object.fromEntries(CATS.map((c) => [c, Number(counts[c]) || 0])) as Record<Cat, number>;
  const catsOnHand = Object.fromEntries(
    CATS.map((c) => [c, starting ? typedCats[c] : onHand[c]])
  ) as Record<Cat, number>;
  const onHandTotal = starting
    ? reportMode === "total"
      ? Number(totalCount) || 0
      : CATS.reduce((s, c) => s + typedCats[c], 0)
    : ALL.reduce((s, b) => s + onHand[b], 0);

  // More animals reported leaving than were on the farm (in a category, or in total).
  const shortBucket = starting ? undefined : ALL.find((b) => onHand[b] < 0);
  const impossible = shortBucket !== undefined;
  const shortMsg = shortBucket
    ? `You reported ${outOf(shortBucket)} ${
        reportMode === "category" ? LABELS[shortBucket].toLowerCase() : "swine"
      } leaving, but only ${openingOf(shortBucket) + inOf(shortBucket)} on record.`
    : "";

  const changeNote = (b: CatOrUnclassified) =>
    inOf(b) || outOf(b)
      ? ` (was ${openingOf(b)}${inOf(b) ? `, +${inOf(b)}` : ""}${outOf(b) ? `, −${outOf(b)}` : ""})`
      : "";

  // ---------- Movement form ----------
  const removing = mvType !== "" && !IS_IN.has(mvType);

  // Removing: only offer groups that have animals. Adding: the five real categories.
  const catOptions: CatOrUnclassified[] = removing ? ALL.filter((b) => onHand[b] > 0) : [...CATS];

  const available: number | null = !removing
    ? null
    : reportMode === "total"
    ? onHand.unclassified
    : mvCat
    ? onHand[mvCat]
    : null;

  const qty = Number(mvQty);
  const overAvailable = available !== null && qty > available;
  const canAddLine =
    mvType !== "" && qty > 0 && (reportMode === "total" || mvCat !== "") && !overAvailable;

  const addLine = () => {
    if (!canAddLine) return;
    setLines((l) => [
      ...l,
      {
        movement_type: mvType,
        category:
          reportMode === "category" && mvCat !== "" && mvCat !== "unclassified" ? mvCat : null,
        quantity: qty,
      },
    ]);
    setMvQty("");
  };

  const removeLine = (i: number) => setLines((l) => l.filter((_, idx) => idx !== i));

  // Starting count only: the typed fields differ between modes, so switching clears them.
  const hasEntries = totalCount !== "" || CATS.some((c) => counts[c] !== "");
  const switchMode = (next: Mode) => {
    if (next === mode) return;
    if (hasEntries && !window.confirm("Switching will clear the numbers you entered. Continue?")) return;
    setMode(next);
    setTotalCount("");
    setCounts(emptyCats());
  };

  const submitReport = async (e: React.FormEvent) => {
    e.preventDefault();
    const fail = (text: string) => {
      setMsg({ type: "err", text });
      window.scrollTo({ top: 0, behavior: "smooth" });
    };

    if (starting && onHandTotal === 0) {
      fail(
        reportMode === "total"
          ? "Enter the total number of swine on hand."
          : "Enter the number of swine on hand for at least one category."
      );
      return;
    }
    if (impossible) {
      fail(shortMsg);
      return;
    }

    setSaving(true);
    try {
      const res = await axios.post(
        `${API}/farmer/period-report`,
        {
          period_type: periodType,
          period_end: periodEnd,
          report_mode: reportMode,
          total: onHandTotal, // includes animals "not broken down"
          counts: reportMode === "category" ? catsOnHand : {},
          movements: starting ? [] : lines,
          remarks: remarks.trim() || null,
        },
        auth(token)
      );
      if (res.data.population) {
        setMe((m) => (m ? { ...m, population: res.data.population } : m));
      }
      setTotalCount("");
      setCounts(emptyCats());
      setLines([]);
      setMvType("");
      setMvCat("");
      setRemarks("");
      setMsg({
        type: "ok",
        text:
          res.data.status === "verified"
            ? "Report saved. Your swine count has been updated."
            : "Report submitted. MAO staff will review it, and your count updates once it is verified.",
      });
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err: any) {
      fail(err.response?.data?.detail || "Could not save the report.");
    } finally {
      setSaving(false);
    }
  };

  // ---------- Breakdown panel ----------
  const draftSum = CATS.reduce((s, c) => s + (Number(draft[c]) || 0), 0);
  const remaining = unclassified - draftSum;
  const canSaveBreakdown = draftSum > 0 && remaining >= 0;

  const saveBreakdown = async () => {
    try {
      const body = Object.fromEntries(CATS.map((c) => [c, Number(draft[c]) || 0]));
      const res = await axios.post(`${API}/farmer/herd-breakdown`, body, auth(token));
      setMe((m) => (m ? { ...m, population: res.data.population } : m));
      setDraft(emptyCats());
      setShowBreakdown(false);
      setMsg({ type: "ok", text: "Herd breakdown saved." });
    } catch (err: any) {
      setMsg({ type: "err", text: err.response?.data?.detail || "Could not save the breakdown." });
    }
  };

  return (
    <div className="login-card report-card">
      <h2 className="login-title">Swine Population Reporting</h2>
      {banner}

      <p><strong>Farmer:</strong> {me.farmer_name}</p>
      <p><strong>Address:</strong> {me.address}</p>
      <p><strong>Current swine count:</strong> {pop.total}</p>

      {pop.has_breakdown && (
        <ul style={{ marginTop: 0 }}>
          {CATS.map((c) => <li key={c}>{LABELS[c]}: {pop[c] ?? 0}</li>)}
          {unclassified > 0 && <li>{LABELS.unclassified}: {unclassified}</li>}
        </ul>
      )}

      {/* Offer a breakdown to total-only farmers, and to by-class farmers with animals not yet broken down */}
      {unclassified > 0 && !showBreakdown && (
        <button type="button" className="link-action" onClick={() => setShowBreakdown(true)}>
          {pop.has_breakdown
            ? `Break down the remaining ${unclassified} swine`
            : "Add herd breakdown (boar, sow, gilts, piglets, grower/fattener)"}
        </button>
      )}

      {showBreakdown && (
        <div style={{ marginBottom: 16 }}>
          <p style={{ marginTop: 0 }}>
            Split your <strong>{unclassified}</strong> swine into categories.
            {pop.has_breakdown
              ? " Animals you leave out stay under “Not broken down”."
              : " Animals you leave out stay in your total count."}
          </p>
          <div className="login-fields">
            {CATS.map((c) => (
              <input
                key={c}
                type="number"
                min={0}
                placeholder={LABELS[c]}
                aria-label={LABELS[c]}
                value={draft[c]}
                onChange={(e) => setDraft((d) => ({ ...d, [c]: e.target.value }))}
              />
            ))}
          </div>
          <p style={{ color: remaining < 0 ? "#b91c1c" : undefined }}>
            Assigned: {draftSum} of {unclassified}
            {remaining < 0
              ? ` — ${Math.abs(remaining)} too many`
              : remaining > 0 ? ` — ${remaining} not broken down` : ""}
          </p>
          <button type="button" className="login-primary" disabled={!canSaveBreakdown}
                  onClick={saveBreakdown}>
            Save breakdown
          </button>{" "}
          <button type="button" className="link-action link-action--muted" onClick={() => setShowBreakdown(false)}>
            Cancel
          </button>
        </div>
      )}

      <form onSubmit={submitReport}>
        {/* 1. Period */}
        <h3 style={{ margin: "20px 0 8px" }}>Report period</h3>
        <div className="login-fields">
          <select value={periodType} aria-label="Report type"
                  onChange={(e) => setPeriodType(e.target.value as "monthly" | "quarterly")}>
            <option value="monthly">Monthly report</option>
            <option value="quarterly">Quarterly report</option>
          </select>
          <input type="date" value={periodEnd} max={today()} required
                 aria-label="Count date (end of period)" title="Count date (end of period)"
                 onChange={(e) => setPeriodEnd(e.target.value)} />
          {starting && (
            <select value={mode} aria-label="How to report your swine"
                    onChange={(e) => switchMode(e.target.value as Mode)}>
              <option value="total">Report total only</option>
              <option value="category">Report by category</option>
            </select>
          )}
        </div>
        <p style={{ marginTop: 0 }}>
          Covers <strong>{periodLabel(periodType, periodEnd)}</strong>. The date is the last day of the
          period.{" "}
          {!starting &&
            (reportMode === "category"
              ? "You report by category."
              : "You report the total only. To report by category, add a herd breakdown above.")}
        </p>

        {/* 2. Swine on hand */}
        <h3 style={{ margin: "20px 0 8px" }}>Swine on hand on that date</h3>
        {starting ? (
          <>
            <p style={{ marginTop: 0 }}>
              No count on record yet. Enter your starting count. Movements are tracked from your next report.
            </p>
            {reportMode === "total" ? (
              <div className="login-fields">
                <input type="number" min={0} placeholder="Total swine on hand" aria-label="Total swine on hand"
                       value={totalCount} onChange={(e) => setTotalCount(e.target.value)} />
              </div>
            ) : (
              <>
                <div className="login-fields">
                  {CATS.map((c) => (
                    <input
                      key={c}
                      type="number"
                      min={0}
                      placeholder={LABELS[c]}
                      aria-label={LABELS[c]}
                      value={counts[c]}
                      onChange={(e) => setCounts((d) => ({ ...d, [c]: e.target.value }))}
                    />
                  ))}
                </div>
                <p style={{ marginTop: 0 }}><strong>Total:</strong> {onHandTotal}</p>
              </>
            )}
          </>
        ) : reportMode === "total" ? (
          <p style={{ marginTop: 0 }}>
            Opening {pop.total} + added {totalIn} − left {totalOut} = <strong>{onHandTotal}</strong> swine
            on hand. This updates as you add movements below.
          </p>
        ) : (
          <>
            <p style={{ marginTop: 0 }}>
              Calculated from your current count by category. It updates as you add movements below.
            </p>
            <ul style={{ marginTop: 0 }}>
              {CATS.map((c) => (
                <li key={c} style={{ color: onHand[c] < 0 ? "#b91c1c" : undefined }}>
                  {LABELS[c]}: <strong>{onHand[c]}</strong>{changeNote(c)}
                </li>
              ))}
              {(openingOf("unclassified") > 0 || onHand.unclassified !== 0) && (
                <li style={{ color: onHand.unclassified < 0 ? "#b91c1c" : undefined }}>
                  {LABELS.unclassified}: <strong>{onHand.unclassified}</strong>{changeNote("unclassified")}
                </li>
              )}
            </ul>
            <p style={{ marginTop: 0 }}><strong>Total on hand:</strong> {onHandTotal}</p>
          </>
        )}

        {/* 3. Movement during the period */}
        {!starting && (
          <>
            <h3 style={{ margin: "20px 0 8px" }}>Movement during the period</h3>
            <p style={{ marginTop: 0 }}>
              Add each birth, purchase, sale, death and so on. Skip this if nothing moved.
            </p>
            <div className="login-fields">
              <select value={mvType} aria-label="Movement type"
                      onChange={(e) => { setMvType(e.target.value); setMvCat(""); }}>
                <option value="">Select movement</option>
                <optgroup label="Added to the farm">
                  {IN_TYPES.map(([t, label]) => <option key={t} value={t}>{label}</option>)}
                </optgroup>
                <optgroup label="Left the farm">
                  {OUT_TYPES.map(([t, label]) => <option key={t} value={t}>{label}</option>)}
                </optgroup>
              </select>

              {reportMode === "category" && (
                <select value={mvCat} aria-label="Movement category"
                        onChange={(e) => setMvCat(e.target.value as CatOrUnclassified | "")}>
                  <option value="">Select category</option>
                  {catOptions.map((b) => (
                    <option key={b} value={b}>
                      {LABELS[b]}{removing ? ` (${onHand[b]})` : ""}
                    </option>
                  ))}
                </select>
              )}

              <input type="number" min={1} max={available ?? undefined}
                     placeholder="Number of swine" aria-label="Number of swine moved"
                     value={mvQty} onChange={(e) => setMvQty(e.target.value)}
                     onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addLine(); } }} />
            </div>

            {overAvailable && (
              <p role="alert" style={{ color: "#b91c1c", marginTop: 0 }}>
                You only have {available} on hand
                {reportMode === "category" && mvCat ? ` for ${LABELS[mvCat]}` : ""}.
              </p>
            )}

            <button type="button" className="link-action" disabled={!canAddLine} onClick={addLine}>
              Add movement
            </button>

            {lines.length > 0 && (
              <>
                <ul>
                  {lines.map((l, i) => (
                    <li key={i}>
                      {MOVEMENT_LABEL[l.movement_type]}
                      {reportMode === "category" ? `, ${LABELS[bucketOf(l)]}` : ""}: {l.quantity}{" "}
                      <button type="button" className="link-action link-action--muted"
                              onClick={() => removeLine(i)}>
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
                <p style={{ marginTop: 0 }}>Added: {totalIn}. Left the farm: {totalOut}.</p>
              </>
            )}
          </>
        )}

        {impossible && (
          <p role="alert" style={{ color: "#b91c1c" }}>{shortMsg} Please check the movements.</p>
        )}

        <div className="login-fields">
          <input style={{ gridColumn: "1 / -1" }}
                 placeholder="Remarks (optional)" aria-label="Remarks"
                 value={remarks} onChange={(e) => setRemarks(e.target.value)} />
        </div>

        <button type="submit" className="login-primary" disabled={impossible || saving}>
          {saving ? "Saving..." : "Submit report"}
        </button>
      </form>
    </div>
  );
}

export default FarmerLivestock;