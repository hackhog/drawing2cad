// Oberfläche der Demo: lädt Zeichnungs-PDFs hoch (auch mehrere auf einmal) und zeigt das Extraktor-Ergebnis
// als SVG in Blatt-mm, geführt in Schritten: Zeichnung → Erkannt → Prüfen (<body data-step>).
// Zwei Seiten (<body data-view>): „Übersicht“ mit Kennzahlen und Tabelle über den ganzen Stapel,
// „Zeichnung“ mit dem Blatt und der Prüfliste. Fertige Zeichnungen melden sich per Toast.
"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";

// Farben wie im Overlay-PNG des Extraktors (render.py), damit beide Ansichten gleich lesbar sind
const KINDS = [
  ["contour", "Kontur", "#141414"],
  ["hidden", "verdeckt", "#965a00"],
  ["centerline", "Mittellinie", "#00aa50"],
  ["hatch", "Schraffur", "#0096dc"],
  ["dimension", "Maßlinie", "#e628a0"],
  ["arrow", "Pfeil", "#e628a0"],
  ["extension", "Maßhilfslinie", "#f08cc8"],
  ["cutting_plane", "Schnittverlauf", "#8c28dc"],
  ["unclear", "unklar", "#ff0000"],
];
const OFF_BY_DEFAULT = new Set(["hatch"]);

// Gleichzeitige Anfragen beim Stapel-Upload: der Extraktor läuft serverseitig im Threadpool,
// zwei parallel halten die Wartezeit kurz, ohne den Container zu überlasten
const PARALLEL_UPLOADS = 2;

const $ = (id) => document.getElementById(id);
const svg = $("sheet");
let sheet = [420, 297];
let viewBox = [0, 0, 420, 297];
let current = null; // API-Antwort der angezeigten Zeichnung

function el(name, attrs = {}, parent = null) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

function html(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

const partName = (filename) => filename.replace(/_dwg\.pdf$/i, "").replace(/\.pdf$/i, "");

// --- Geometrie → SVG-Pfad ------------------------------------------------------------

function pt(cx, cy, r, deg) {
  const a = (deg * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

function strokePath(s) {
  if (s.type === "line") return `M${s.p0[0]} ${s.p0[1]}L${s.p1[0]} ${s.p1[1]}`;
  const [cx, cy] = s.center;
  const r = s.radius;
  if (s.type === "circle") {
    return `M${cx - r} ${cy}A${r} ${r} 0 1 1 ${cx + r} ${cy}A${r} ${r} 0 1 1 ${cx - r} ${cy}`;
  }
  // Winkel im y-nach-unten-System, positiv = im Uhrzeigersinn ab 3 Uhr (wie im Extraktor)
  const [x0, y0] = pt(cx, cy, r, s.start_deg);
  const [x1, y1] = pt(cx, cy, r, s.start_deg + s.sweep_deg);
  const large = Math.abs(s.sweep_deg) > 180 ? 1 : 0;
  const sweep = s.sweep_deg > 0 ? 1 : 0;
  return `M${x0} ${y0}A${r} ${r} 0 ${large} ${sweep} ${x1} ${y1}`;
}

// --- Zoom und Verschieben über die viewBox -----------------------------------------

function setViewBox(vb) {
  viewBox = vb;
  svg.setAttribute("viewBox", vb.join(" "));
}

function fitBox([x0, y0, x1, y1], margin = 8) {
  setViewBox([x0 - margin, y0 - margin, x1 - x0 + 2 * margin, y1 - y0 + 2 * margin]);
}

const fitSheet = () => fitBox([0, 0, sheet[0], sheet[1]], 4);

function toSheet(evt) {
  const r = svg.getBoundingClientRect();
  // preserveAspectRatio "xMidYMid meet": gemeinsamer Maßstab, Rest zentriert
  const scale = Math.min(r.width / viewBox[2], r.height / viewBox[3]);
  const ox = (r.width - viewBox[2] * scale) / 2;
  const oy = (r.height - viewBox[3] * scale) / 2;
  return [viewBox[0] + (evt.clientX - r.left - ox) / scale, viewBox[1] + (evt.clientY - r.top - oy) / scale, scale];
}

svg.addEventListener("wheel", (evt) => {
  evt.preventDefault();
  const [mx, my] = toSheet(evt);
  const f = Math.exp(evt.deltaY * 0.0015);
  const [x, y, w, h] = viewBox;
  setViewBox([mx - (mx - x) * f, my - (my - y) * f, w * f, h * f]);
}, { passive: false });

let drag = null;
svg.addEventListener("pointerdown", (evt) => {
  drag = { x: evt.clientX, y: evt.clientY, vb: viewBox.slice(), scale: toSheet(evt)[2] };
  svg.setPointerCapture(evt.pointerId);
  svg.classList.add("panning");
});
svg.addEventListener("pointermove", (evt) => {
  if (!drag) return;
  const dx = (evt.clientX - drag.x) / drag.scale;
  const dy = (evt.clientY - drag.y) / drag.scale;
  setViewBox([drag.vb[0] - dx, drag.vb[1] - dy, drag.vb[2], drag.vb[3]]);
});
const endDrag = () => { drag = null; svg.classList.remove("panning"); };
svg.addEventListener("pointerup", endDrag);
svg.addEventListener("pointercancel", endDrag);
svg.addEventListener("dblclick", fitSheet);
$("fit").addEventListener("click", () => { clearFocus(); fitSheet(); });

// --- Darstellung --------------------------------------------------------------------

function renderSheet(result) {
  const d = result.drawing;
  sheet = d.sheet_size_mm;
  svg.replaceChildren();

  el("rect", { class: "paper", x: 0, y: 0, width: sheet[0], height: sheet[1] }, svg);
  el("image", { class: "page", href: result.page_png, x: 0, y: 0, width: sheet[0], height: sheet[1] }, svg);
  const overlay = el("g", { class: "overlay" }, svg);

  const byKind = Object.fromEntries(KINDS.map(([k]) => [k, []]));
  for (const s of d.strokes) (byKind[s.kind] ??= []).push(strokePath(s));

  const toolbar = $("kinds");
  toolbar.replaceChildren();
  for (const [kind, label, color] of KINDS) {
    const paths = byKind[kind];
    if (!paths.length) continue;
    const g = el("g", { class: `k k-${kind}` }, overlay);
    el("path", { d: paths.join(""), stroke: color }, g);
    const on = !OFF_BY_DEFAULT.has(kind);
    g.style.display = on ? "" : "none";

    const chip = html("button", undefined, { class: "chip", type: "button", "aria-pressed": String(on), title: label });
    chip.append(Object.assign(document.createElement("i"), { style: `background:${color}` }), html("span", label), html("b", paths.length));
    chip.addEventListener("click", () => {
      const now = chip.getAttribute("aria-pressed") !== "true";
      chip.setAttribute("aria-pressed", String(now));
      g.style.display = now ? "" : "none";
    });
    toolbar.appendChild(chip);
  }

  const texts = el("g", {}, overlay);
  for (const t of d.text_blocks) {
    const [x0, y0, x1, y1] = t.bbox;
    const r = el("rect", { class: "text-box", x: x0, y: y0, width: x1 - x0, height: y1 - y0 }, texts);
    el("title", {}, r).textContent = t.text;
  }

  for (const v of d.views) {
    const [x0, y0, x1, y1] = v.bbox;
    el("rect", { class: "view-box", x: x0, y: y0, width: x1 - x0, height: y1 - y0 }, overlay);
    el("text", { class: "view-label", x: x0 + 1, y: y0 - 1.5 }, overlay).textContent = v.is_iso ? `${v.id} · 3D` : String(v.id);
  }

  el("g", { id: "focus" }, svg);
  fitSheet();
}

function clearFocus() {
  $("focus")?.replaceChildren();
  for (const li of document.querySelectorAll(".list li.active")) li.classList.remove("active");
}

function focusOn(bbox, strokeIds = []) {
  const layer = $("focus");
  layer.replaceChildren();
  const [x0, y0, x1, y1] = bbox;
  el("rect", { class: "focus", x: x0 - 1, y: y0 - 1, width: x1 - x0 + 2, height: y1 - y0 + 2 }, layer);
  if (strokeIds.length) {
    const wanted = new Set(strokeIds);
    const d = current.drawing.strokes.filter((s) => wanted.has(s.id)).map(strokePath).join("");
    el("path", { class: "focus-strokes", d }, layer);
  }
  // Mindestens 30 mm Umgebung, damit man die Stelle in der Zeichnung wiederfindet
  fitBox(bbox, Math.max(30, (x1 - x0) * 0.6, (y1 - y0) * 0.6));
}

const FLAG_KIND = {
  unclear_strokes: "Striche keiner Klasse sicher zuordenbar",
  unreadable_text: "Zeichen nicht sicher erkannt",
};

function renderFlags(result) {
  const flags = $("flags");
  flags.replaceChildren();
  $("flag-count").textContent = result.review.length ? String(result.review.length) : "";
  if (!result.review.length) flags.appendChild(html("li", "Nichts zu prüfen.", { class: "ok" }));
  for (const f of result.review) {
    if (!f.bbox) {
      flags.appendChild(html("li", f.message, { class: "ok" }));
      continue;
    }
    const li = html("li");
    const [x0, y0] = f.bbox;
    li.append(
      html("i", undefined, { class: `dot ${f.kind}` }),
      Object.assign(html("div"), { className: "item" }),
      html("time", `x ${Math.round(x0)} · y ${Math.round(y0)}`),
    );
    li.querySelector(".item").append(html("strong", f.message), html("span", FLAG_KIND[f.kind] ?? f.kind));
    li.addEventListener("click", () => {
      clearFocus();
      li.classList.add("active");
      focusOn(f.bbox, f.stroke_ids);
    });
    flags.appendChild(li);
  }
}

// --- Übersicht: Kennzahlen und Tabelle über den ganzen Stapel ------------------------

const fmt = (n) => n.toLocaleString("de-DE");
const pct = (x) => `${(x * 100).toLocaleString("de-DE", { maximumFractionDigits: 1 })} %`;

function explainedShare(result) {
  const { strokes, by_kind: byKind } = result.drawing.summary;
  return { total: strokes, explained: strokes - (byKind.unclear ?? 0) };
}

function renderOverview() {
  const done = jobs.filter((j) => j.state === "done");
  const busy = jobs.filter((j) => j.state === "wait" || j.state === "run").length;
  const failed = jobs.filter((j) => j.state === "error").length;
  document.body.toggleAttribute("data-has-jobs", jobs.length > 0);

  $("jobs-value").textContent = jobs.length ? fmt(done.length) : "–";
  if (busy) setDelta($("jobs-sub"), `${busy} in Arbeit`, "");
  else if (failed) setDelta($("jobs-sub"), `${failed} nicht lesbar`, "bad");
  else setDelta($("jobs-sub"), jobs.length ? "alle gelesen, lokal und ohne KI" : "gelesen, lokal und ohne KI", jobs.length ? "good" : "");

  const strokes = done.map((j) => explainedShare(j.result));
  const total = strokes.reduce((a, s) => a + s.total, 0);
  const explained = strokes.reduce((a, s) => a + s.explained, 0);
  const share = total ? explained / total : 0;
  $("explained-value").textContent = total ? pct(share) : "–";
  $("explained-sub").textContent = total ? `${fmt(explained)} von ${fmt(total)} Strichen zugeordnet` : "Anteil der Striche mit sicherer Bedeutung";
  $("gauge-fill").style.strokeDasharray = `${share * 100} 100`;

  const texts = done.flatMap((j) => j.result.drawing.text_blocks);
  const unsure = texts.filter((t) => t.text.includes("?")).length;
  $("texts-value").textContent = done.length ? fmt(texts.length) : "–";
  if (done.length) setDelta($("texts-sub"), unsure ? `${unsure} nicht sicher gelesen` : "alle sicher gelesen", unsure ? "bad" : "good");

  const flags = done.reduce((a, j) => a + j.result.review.length, 0);
  $("review-value").textContent = done.length ? fmt(flags) : "–";
  if (done.length) setDelta($("review-sub"), flags === 1 ? "Stelle markiert statt geraten" : flags ? "Stellen markiert statt geraten" : "nichts offen", flags ? "bad" : "good");
  $("tile-review").classList.toggle("warn", flags > 0);

  $("job-rows").replaceChildren(...jobs.map(jobRow));
  if (document.body.dataset.view === "overview") renderHead();
}

function jobRow(job) {
  const [state, label] = jobStatus(job);
  const tr = html("tr", undefined, { "data-state": state });
  const cell = (text, cls) => html("td", text, cls ? { class: cls } : {});
  const status = cell("");
  status.appendChild(html("span", label, { class: `status ${state}`, title: job.error ?? "" }));
  if (job.state !== "done") {
    tr.append(cell(partName(job.name), "name"), status, ...Array.from({ length: 5 }, () => cell("–", "num")));
    return tr;
  }
  const d = job.result.drawing;
  const { total, explained } = explainedShare(job.result);
  tr.append(
    cell(partName(job.name), "name"), status,
    cell(pct(total ? explained / total : 1), "num"), cell(fmt(d.views.length), "num"),
    cell(fmt(d.text_blocks.length), "num"), cell(fmt(job.result.review.length), "num"), cell(`${job.seconds} s`, "num"),
  );
  tr.tabIndex = 0;
  tr.addEventListener("click", () => show(job));
  tr.addEventListener("keydown", (evt) => evt.key === "Enter" && show(job));
  return tr;
}

function setDelta(node, text, tone) {
  node.textContent = text;
  node.className = tone ? `delta ${tone}` : "";
}

for (const b of document.querySelectorAll(".tile-mode button")) {
  b.addEventListener("click", () => {
    for (const other of b.parentElement.children) other.setAttribute("aria-checked", String(other === b));
    $("tile-explained").dataset.mode = b.dataset.mode;
  });
}

// --- Seiten: Übersicht und Zeichnung ------------------------------------------------

function renderHead() {
  if (document.body.dataset.view === "overview") {
    const done = jobs.filter((j) => j.state === "done").length;
    $("title").textContent = "Übersicht";
    $("updated").textContent = jobs.length ? `${done} von ${jobs.length} Zeichnungen gelesen` : "Noch keine Zeichnung hochgeladen";
    $("updated").classList.toggle("live", done > 0);
    return;
  }
  const { total, explained } = explainedShare(current);
  $("title").textContent = partName(shown.name);
  $("updated").textContent = `Gelesen ${shown.doneAt} · ${shown.seconds} s · ${pct(total ? explained / total : 1)} erklärt · lokal, ohne KI`;
  $("updated").classList.add("live");
}

function setView(view) {
  document.body.dataset.view = view;
  $("nav-overview").setAttribute("aria-current", String(view === "overview"));
  for (const job of jobs) renderJob(job);
  renderHead();
  if (view === "drawing") requestAnimationFrame(fitSheet); // Viewer hat erst jetzt seine Größe
}

$("nav-overview").addEventListener("click", () => setView("overview"));

// --- Toasts -------------------------------------------------------------------------

function toast(title, detail, tone) {
  const node = html("div", undefined, { class: `toast ${tone}` });
  node.append(html("strong", title), html("span", detail));
  $("toasts").appendChild(node);
  setTimeout(() => node.classList.add("out"), 4500);
  setTimeout(() => node.remove(), 5000);
}

// --- Geführte Schritte --------------------------------------------------------------

function storyText(step) {
  if (!current) return "";
  const d = current.drawing;
  const n = current.review.length;
  return {
    1: `Eine Zeichnung ohne 3D-Modell: ${d.sheet_size_mm[0]} × ${d.sheet_size_mm[1]} mm, keine Textebene, nur Striche.`,
    2: `${d.summary.strokes.toLocaleString("de-DE")} Striche klassifiziert, ${d.summary.views} Ansichten gefunden, ${d.summary.text_blocks} Maße und Texte gelesen. Ohne KI, nachvollziehbar.`,
    3: n ? `${n} Stelle(n) ohne sichere Bedeutung: markiert statt geraten.` : "Keine unklaren Stellen: alles erklärt.",
  }[step];
}

function setStep(step) {
  document.body.dataset.step = String(step);
  for (const b of document.querySelectorAll(".steps button[data-step]")) {
    b.setAttribute("aria-current", b.dataset.step === String(step) ? "step" : "false");
  }
  $("story-text").textContent = storyText(step);
  $("next").hidden = step >= 3;
  clearFocus();
  if (step === 3 && current?.review[0]?.bbox) {
    $("flags").querySelector("li")?.click();
  } else if (current) {
    fitSheet();
  }
}

for (const b of document.querySelectorAll(".steps button[data-step]")) {
  b.addEventListener("click", () => current && setStep(Number(b.dataset.step)));
}
$("next").addEventListener("click", () => setStep(Number(document.body.dataset.step) + 1));

// --- Stapel: Upload-Warteschlange ----------------------------------------------------
// Jeder Eintrag durchläuft wait → run → done | error. Die Übersicht füllt sich live; ein Klick auf eine
// fertige Zeichnung (Seitenleiste oder Tabelle) öffnet sie, der aktuelle Schritt bleibt beim Wechsel erhalten.

const jobs = [];
let shown = null;

function jobStatus(job) {
  if (job.state === "wait") return ["wait", "wartet"];
  if (job.state === "run") return ["run", "liest"];
  if (job.state === "error") return ["error", "Fehler"];
  const n = job.result.review.length;
  return n ? ["flag", `${n} prüfen`] : ["done", "fertig"];
}

function renderJob(job) {
  const [state, label] = jobStatus(job);
  const button = job.li.firstChild;
  button.dataset.state = state;
  button.disabled = job.state !== "done";
  button.title = job.error ?? job.name;
  button.setAttribute("aria-current", String(job === shown && document.body.dataset.view === "drawing"));
  button.replaceChildren(html("span", partName(job.name)), html("small", label));
}

function show(job) {
  shown = job;
  current = job.result;
  renderSheet(current);
  renderFlags(current);
  setView("drawing");
  setStep(Number(document.body.dataset.step));
}

async function run(job) {
  job.state = "run";
  renderJob(job);
  renderOverview();
  const started = performance.now();
  try {
    const body = new FormData();
    body.append("file", job.file);
    const res = await fetch("api/extract", { method: "POST", body });
    const json = await res.json();
    if (!res.ok) throw new Error(json.detail || res.statusText);
    job.result = json;
    job.state = "done";
    job.seconds = ((performance.now() - started) / 1000).toLocaleString("de-DE", { maximumFractionDigits: 1 });
    job.doneAt = new Date().toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  } catch (err) {
    job.error = err.message;
    job.state = "error";
  }
  job.file = null; // PDF nicht länger als nötig im Speicher halten
  renderJob(job);
  renderOverview();
  if (job.state === "done") {
    const n = job.result.review.length;
    toast(`${partName(job.name)} gelesen`, n ? `${n} Stelle(n) zu prüfen · ${job.seconds} s` : `Alles erklärt · ${job.seconds} s`, n ? "warn" : "good");
  } else {
    toast(`${partName(job.name)} nicht lesbar`, job.error, "bad");
  }
  pump();
}

function pump() {
  let running = jobs.filter((j) => j.state === "run").length;
  for (const job of jobs) {
    if (running >= PARALLEL_UPLOADS) break;
    if (job.state !== "wait") continue;
    running += 1;
    run(job);
  }
}

function addFiles(files) {
  for (const file of files) {
    const job = { file, name: file.name, state: "wait", result: null, error: null, li: html("li") };
    const button = html("button", undefined, { type: "button" });
    button.addEventListener("click", () => show(job));
    job.li.appendChild(button);
    $("batch").appendChild(job.li);
    jobs.push(job);
    renderJob(job);
  }
  if (jobs.length) $("upload-label").textContent = "+ Weitere PDFs";
  renderOverview();
  pump();
}

$("file").addEventListener("change", (evt) => {
  addFiles([...evt.target.files]);
  evt.target.value = "";
});

for (const target of [$("upload"), $("viewer"), $("dropzone")]) {
  target.addEventListener("dragover", (evt) => { evt.preventDefault(); $("upload").classList.add("drag"); });
  target.addEventListener("dragleave", () => $("upload").classList.remove("drag"));
  target.addEventListener("drop", (evt) => {
    evt.preventDefault();
    $("upload").classList.remove("drag");
    addFiles([...evt.dataTransfer.files]);
  });
}

setStep(1);
setView("overview");
renderOverview();
