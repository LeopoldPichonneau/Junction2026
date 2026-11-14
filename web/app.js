// TimeProof public site. Plain JS, no build step.
// Every text coming from Wikipedia or a model is inserted with textContent, never innerHTML.

"use strict";

// ---------- Data access ----------

const params = new URLSearchParams(location.search);
const IS_LOCAL = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
// Mocks are only allowed locally or when asked for explicitly, so the deployed site
// can never show invented cases if the API is down.
const MOCK_ALLOWED = IS_LOCAL || params.get("mock") === "1";
let usingMock = params.get("mock") === "1";

function mockPath(path) {
  const url = new URL(path, location.origin);
  const p = url.pathname;
  let m;
  if (p === "/api/stats") return "mock/stats.json";
  if (p === "/api/cases") return "mock/cases.json";
  if ((m = p.match(/^\/api\/cases\/(\d+)$/))) return `mock/case-${m[1]}.json`;
  if (p === "/api/quality") return "mock/quality.json";
  if (p === "/api/articles") return "mock/articles.json";
  if ((m = p.match(/^\/api\/articles\/(\d+)\/timeline$/))) return `mock/timeline-${m[1]}.json`;
  if ((m = p.match(/^\/api\/articles\/(\d+)$/))) return `mock/article-${m[1]}.json`;
  return null;
}

async function fetchJson(url) {
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
  return r.json();
}

// Single entry point for every API call.
async function api(path) {
  if (!usingMock) {
    try {
      return await fetchJson(path);
    } catch (err) {
      if (!MOCK_ALLOWED) throw err;
      usingMock = true;
    }
  }
  const file = mockPath(path);
  if (!file) throw new Error(`No mock file for ${path}`);
  showMockBanner();
  return fetchJson(file);
}

// ---------- Small helpers ----------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

const fmt = (n) => (typeof n === "number" ? n.toLocaleString("en-US") : "–");

function readersText(readers) {
  // Pageview data only exists from July 2015, and it counts views of the whole article: an upper bound.
  if (readers === null || readers === undefined) return "no reader data (before Jul 2015)";
  return `≈ ${fmt(readers)} readers`;
}

// Under a day, "0 days" would hide a short but real exposure: count hours instead.
function durationText(days) {
  if (typeof days !== "number") return "? days";
  if (days < 1) {
    const h = Math.max(1, Math.round(days * 24));
    return `${h} ${h === 1 ? "hour" : "hours"}`;
  }
  const d = Math.round(days);
  return `${fmt(d)} ${d === 1 ? "day" : "days"}`;
}

function exposureText(days, readers, stillOnline) {
  const d = durationText(days);
  const online = stillOnline ? `still online after ${d}` : `online for ${d}`;
  return `${online} · ${readersText(readers)}`;
}

function formatDate(iso) {
  if (!iso) return "–";
  const d = new Date(iso.length === 10 ? iso + "T00:00:00Z" : iso);
  if (isNaN(d)) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

// Wikimedia's "Artist" field is HTML; keep only its text.
function plainText(html) {
  if (!html) return "";
  return (new DOMParser().parseFromString(String(html), "text/html").body.textContent || "").trim();
}

const SIGNAL_LABELS = {
  image: "Image / caption",
  framing: "Framing drift",
  sources: "Sources removed",
  coordination: "Coordinated edits",
};

const ACCOUNT_LABELS = {
  declared_bot: "Declared Wikipedia bot",
  bot_like: "Bot-like editing rhythm",
  throwaway: "Short-lived account",
  single_purpose: "Single-topic account",
  normal: "No unusual pattern",
};

function errorBox(target, err) {
  target.replaceChildren(el("p", { class: "error", text: "Could not load data. Please try again later." }));
  console.error(err);
}

// ---------- Layout shared by every page ----------

function showMockBanner() {
  if (document.querySelector(".mock-banner")) return;
  document.body.prepend(
    el("div", { class: "mock-banner", title: "Placeholder content for development, not real findings", text: "Sample data · not real findings" })
  );
}

// Hand-drawn line icons (24px grid, Lucide-like style), always shown with a text label.
const ICON_ATTRS = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
const ICONS = {
  home: `<svg ${ICON_ATTRS}><path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/></svg>`,
  timemachine: `<svg ${ICON_ATTRS}><path d="M3 12a9 9 0 1 0 2.6-6.4L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3.5 2"/></svg>`,
  lens: `<svg ${ICON_ATTRS}><circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/><path d="M7.5 10.5h6"/></svg>`,
  quality: `<svg ${ICON_ATTRS}><path d="M12 21s7.5-3.6 7.5-9.5V5.2L12 2.5 4.5 5.2v6.3C4.5 17.4 12 21 12 21z"/><path d="m8.8 11.8 2.2 2.2 4.2-4.3"/></svg>`,
};

function renderLayout() {
  const page = document.body.dataset.page;
  const links = [
    ["index.html", "Cases", "home"],
    ["timemachine.html", "Time machine", "timemachine"],
    ["quality.html", "Detection quality", "quality"],
    ["lens.html", "Lens", "lens"],
  ];
  const header = el(
    "header",
    { class: "site" },
    el(
      "div",
      { class: "inner" },
      el("a", { class: "brand-mark", href: "index.html", title: "TimeProof home", "aria-label": "TimeProof home", text: "TP" }),
      el(
        "nav",
        { "aria-label": "Main" },
        links.map(([href, label, id]) => {
          const a = el("a", { href, class: id === page ? "active" : null, "aria-current": id === page ? "page" : null });
          a.insertAdjacentHTML("afterbegin", ICONS[id]); // static, trusted markup
          a.append(el("span", { text: label }));
          return a;
        })
      )
    )
  );
  const footer = el(
    "footer",
    { class: "site" },
    el("div", { class: "inner" },
    el("p", {}, el("span", { class: "wordmark" }, "Time", el("span", { text: "Proof" })), " · independent evidence about how Wikipedia history is edited."),
    el(
      "p",
      {},
      "Article texts come from ",
      el("a", { href: "https://fi.wikipedia.org/", text: "Finnish Wikipedia" }),
      " and are available under ",
      el("a", { href: "https://creativecommons.org/licenses/by-sa/4.0/", text: "CC BY-SA 4.0" }),
      ". Images are shown with their author and license. No Wikipedia account is ever named on this site."
    ),
    el(
      "p",
      {},
      "Edit history: ",
      el("a", { href: "https://github.com/MariaDB/mariadb-wikipedia-datasets", text: "MariaDB Wikipedia datasets" }),
      ". TimeProof never edits Wikipedia."
    ))
  );
  document.body.prepend(header);
  document.body.append(footer);
  if (usingMock) showMockBanner();
}

// ---------- Home: stats + published cases ----------

function caseItem(c) {
  // The list format has no credit by default: a thumbnail only appears when author and license come with it.
  const author = plainText(c.image_author);
  const thumb = c.image_thumb && author && c.image_license
    ? el("figure", {}, el("img", { src: c.image_thumb, alt: "", loading: "lazy" }), el("figcaption", { text: `${author} · ${c.image_license}` }))
    : null;
  const href = `case.html?rev_id=${encodeURIComponent(c.rev_id)}`;
  // Only the button opens the case: the row itself is plain text.
  return el(
    "div",
    { class: `card case-item${thumb ? " has-image" : ""}` },
    thumb,
    el(
      "div",
      {},
      el(
        "div",
        { class: "meta" },
        el("span", { class: "tag", text: SIGNAL_LABELS[c.signal_type] || c.signal_type }),
        el("span", { text: c.title }),
        el("span", { text: formatDate(c.date) })
      ),
      el("h3", { text: c.headline_en, style: "margin-top: 10px" }),
      el("p", { text: c.summary_en }),
      el(
        "div",
        { class: "row-foot" },
        el("span", { class: "meta readers", text: exposureText(c.days_live, c.readers_est, c.still_online) }),
        el("a", { class: "pill", href, text: "Read the evidence" })
      )
    )
  );
}

// ---------- Home: search, filters and sort over the published cases ----------
// The list is small (about a hundred cases), so everything is filtered in the browser:
// no extra API call, and the URL keeps the filters so a filtered view can be shared.

const SORTS = {
  readers: ["Most readers exposed", (a, b) => (b.readers_est ?? -1) - (a.readers_est ?? -1) || (b.confidence || 0) - (a.confidence || 0)],
  days: ["Longest online", (a, b) => (b.days_live || 0) - (a.days_live || 0)],
  newest: ["Newest edit", (a, b) => String(b.date).localeCompare(String(a.date))],
  oldest: ["Oldest edit", (a, b) => String(a.date).localeCompare(String(b.date))],
  confidence: ["Highest confidence", (a, b) => (b.confidence || 0) - (a.confidence || 0)],
};

function optionList(select, entries, selected) {
  select.replaceChildren(...entries.map(([value, label]) => el("option", { value, text: label })));
  if (entries.some(([v]) => v === selected)) select.value = selected;
}

function setupCaseFilters(cases, casesBox) {
  const form = document.getElementById("case-filters");
  const countBox = document.getElementById("case-count");
  const sortName = document.getElementById("sort-name");

  // Every choice is built from the cases themselves, so no filter can offer an empty category.
  const count = (key) => cases.reduce((m, c) => m.set(c[key], (m.get(c[key]) || 0) + 1), new Map());
  const signals = [...count("signal_type")].sort((a, b) => b[1] - a[1]);
  const titles = [...count("title")].sort((a, b) => String(a[0]).localeCompare(String(b[0]), "fi"));
  const years = [...new Set(cases.map((c) => String(c.date).slice(0, 4)))].sort();

  const q = el("input", { type: "search", id: "f-q", placeholder: "Search a word, an article, a headline…", autocomplete: "off" });
  const signal = el("select", { id: "f-signal" });
  const article = el("select", { id: "f-article" });
  const status = el("select", { id: "f-status" });
  const from = el("select", { id: "f-from" });
  const to = el("select", { id: "f-to" });
  const sort = el("select", { id: "f-sort" });
  const reset = el("button", { type: "button", class: "pill secondary", text: "Reset" });

  optionList(signal, [["", `All signals (${cases.length})`], ...signals.map(([s, n]) => [s, `${SIGNAL_LABELS[s] || s} (${n})`])], params.get("signal"));
  optionList(article, [["", `All articles (${titles.length})`], ...titles.map(([t, n]) => [t, `${t} (${n})`])], params.get("article"));
  optionList(status, [["", "Online or not"], ["online", "Still online"], ["removed", "Since removed"]], params.get("status"));
  optionList(from, years.map((y) => [y, y]), params.get("from") || years[0]);
  optionList(to, years.map((y) => [y, y]), params.get("to") || years[years.length - 1]);
  optionList(sort, Object.entries(SORTS).map(([k, [label]]) => [k, label]), params.get("sort") || "readers");
  q.value = params.get("q") || "";

  const field = (label, control) => el("label", {}, label, control);
  form.replaceChildren(
    el("label", { class: "search" }, "Search", q),
    field("Signal", signal),
    field("Article", article),
    field("Status", status),
    el("div", { class: "years" }, field("From", from), field("To", to)),
    field("Sort by", sort),
    reset
  );

  function apply() {
    const words = q.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const lo = from.value <= to.value ? from.value : to.value;
    const hi = from.value <= to.value ? to.value : from.value;
    const shown = cases.filter((c) => {
      const year = String(c.date).slice(0, 4);
      if (signal.value && c.signal_type !== signal.value) return false;
      if (article.value && c.title !== article.value) return false;
      if (status.value === "online" && !c.still_online) return false;
      if (status.value === "removed" && c.still_online) return false;
      if (year < lo || year > hi) return false;
      const hay = `${c.title} ${c.headline_en} ${c.summary_en}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    });
    shown.sort(SORTS[sort.value][1]);
    sortName.textContent = SORTS[sort.value][0].toLowerCase();
    countBox.textContent = shown.length === cases.length ? `${cases.length} cases` : `${shown.length} of ${cases.length} cases`;
    casesBox.replaceChildren(
      ...(shown.length ? shown.map(caseItem) : [el("p", { class: "empty", text: "No case matches these filters." })])
    );
    // Keep the view in the address bar (shareable), without adding history entries.
    const p = new URLSearchParams();
    if (q.value.trim()) p.set("q", q.value.trim());
    for (const [k, s, def] of [["signal", signal, ""], ["article", article, ""], ["status", status, ""], ["from", from, years[0]], ["to", to, years[years.length - 1]], ["sort", sort, "readers"]]) {
      if (s.value !== def) p.set(k, s.value);
    }
    if (params.get("mock") === "1") p.set("mock", "1");
    history.replaceState(null, "", p.toString() ? `?${p}` : location.pathname);
  }

  q.addEventListener("input", apply);
  for (const s of [signal, article, status, from, to, sort]) s.addEventListener("change", apply);
  reset.addEventListener("click", () => {
    q.value = "";
    signal.value = article.value = status.value = "";
    from.value = years[0];
    to.value = years[years.length - 1];
    sort.value = "readers";
    apply();
  });
  apply();
}

async function pageHome() {
  const statsBox = document.getElementById("stats");
  const casesBox = document.getElementById("cases");
  const newBox = document.getElementById("new-this-week");

  try {
    const s = await api("/api/stats");
    const items = [
      [s.articles, "articles"],
      [s.versions, "versions in MariaDB"],
      [s.analysed, "edits examined by AI"],
      [s.published, "cases published"],
    ];
    if (typeof s.readers_exposed_est === "number" && s.readers_exposed_est > 0) {
      items.push([s.readers_exposed_est, "readers exposed (≈, upper bound)"]);
    }
    statsBox.replaceChildren(
      ...items.map(([v, l]) => el("div", { class: "stat" }, el("div", { class: "value", text: fmt(v) }), el("div", { class: "label", text: l })))
    );
  } catch (err) {
    errorBox(statsBox, err);
  }

  try {
    const cases = await api("/api/cases");
    if (!cases.length) casesBox.replaceChildren(el("p", { class: "empty", text: "No case published yet." }));
    else setupCaseFilters(cases, casesBox);
  } catch (err) {
    errorBox(casesBox, err);
  }

  // Only shown when the hourly monitor really returns something; mocks are skipped on purpose.
  if (newBox && !usingMock) {
    try {
      const recent = await fetchJson("/api/cases?since=7d");
      if (Array.isArray(recent) && recent.length) {
        newBox.replaceChildren(el("h2", { text: "New this week" }), ...recent.map(caseItem));
      }
    } catch (_) {
      // Monitoring is optional: hide the section silently.
    }
  }
}

// ---------- Case page: the evidence ----------

function section(title, ...content) {
  return el("div", { class: "card" }, el("p", { class: "label-small", text: title }), ...content);
}

// An image without author and license must not be displayed: returns null in that case.
function creditedFigure(img) {
  if (!img || !img.thumb_url) return null;
  const author = plainText(img.author);
  if (!author || !img.license) return null;
  return el(
    "figure",
    {},
    el("img", { src: img.thumb_url, alt: img.caption_new || img.file || "" }),
    el("figcaption", {}, `${img.file || ""} · ${author} · ${img.license}`)
  );
}

function captionBlock(img, shown) {
  if (!img) return null;
  return section(
    "Caption",
    shown ? null : el("p", { class: "empty", text: "Image not shown: author or license unknown." }),
    el(
      "div",
      { class: "grid2" },
      el("div", {}, el("p", { class: "label-small", text: "Before" }), el("p", { class: "caption-old", text: img.caption_old || "(none)" })),
      el("div", {}, el("p", { class: "label-small", text: "After" }), el("p", { class: "caption-new", text: img.caption_new || "(none)" }))
    )
  );
}

async function pageCase() {
  const box = document.getElementById("case");
  const revId = params.get("rev_id");
  if (!revId || !/^\d+$/.test(revId)) {
    box.replaceChildren(el("p", { class: "error", text: "Missing case id." }));
    return;
  }
  let c;
  try {
    c = await api(`/api/cases/${revId}`);
  } catch (err) {
    errorBox(box, err);
    return;
  }
  document.title = `${c.headline_en} · TimeProof`;
  const ex = c.exposure || {};
  const inv = c.investigator || {};
  const dec = c.decider || {};
  const acc = c.account || {};
  const findings = inv.image_findings;

  // Wrapped in a div so optional blocks (null) are skipped by el() instead of printed as "null".
  const figure = creditedFigure(c.image);

  box.replaceChildren(el("div", {},
    el(
      "div",
      { class: `case-hero hero-blue${figure ? " has-image" : ""}` },
      figure,
      el(
        "div",
        {},
        el(
          "div",
          { class: "meta" },
          el("span", { class: "tag flag", text: SIGNAL_LABELS[c.signal_type] || c.signal_type }),
          el("span", { text: c.title }),
          el("span", { text: `Edit of ${formatDate(c.date)}` }),
          el("span", { text: `Confidence ${Math.round((c.confidence || 0) * 100)}%` })
        ),
        el("h1", { text: c.headline_en }),
        el("p", { class: "lead", text: c.summary_en })
      )
    ),

    el(
      "div",
      { class: "band exposure-band" },
      el("p", { class: "label-small", text: "Exposure" }),
      el("div", { class: "exposure", text: exposureText(ex.days_live, ex.readers_est, ex.still_online) }),
      el(
        "p",
        { class: "meta" },
        `From ${formatDate(ex.live_from)} to ${ex.still_online ? "today (still online)" : formatDate(ex.live_until)}. ` +
          "Readers are an upper bound: daily views of the whole article over that period."
      )
    ),

    captionBlock(c.image, Boolean(figure)),

    c.added || c.removed
      ? section(
          "What changed",
          el(
            "div",
            { class: "grid2" },
            el("div", {}, el("p", { class: "label-small", text: "Removed" }), el("div", { class: "diff-removed", text: c.removed || "(nothing)" })),
            el("div", {}, el("p", { class: "label-small", text: "Added" }), el("div", { class: "diff-added", text: c.added || "(nothing)" }))
          )
        )
      : null,

    section(
      `Investigator · ${inv.model || "unknown model"}`,
      el("p", { class: "report", text: inv.report || "" }),
      inv.signals && inv.signals.length ? el("ul", { class: "plain" }, inv.signals.map((s) => el("li", { text: s }))) : null,
      findings
        ? el(
            "p",
            {},
            el("strong", { text: "What the image shows: " }),
            findings.what_it_shows || "",
            findings.caption_matches === false ? " The caption does not match the image." : "",
            findings.caption_matches === true ? " The caption matches the image." : ""
          )
        : null
    ),

    section(`Decider · ${dec.model || "unknown model"}`, el("p", { class: "report", text: dec.explanation || "" })),

    section(
      "Account pattern (no account is named)",
      el("p", { text: ACCOUNT_LABELS[acc.kind] || acc.kind || "Unknown" }),
      acc.reasons && acc.reasons.length ? el("ul", { class: "plain" }, acc.reasons.map((r) => el("li", { text: r }))) : null
    ),

    section(
      "Check it yourself on Wikipedia",
      el(
        "p",
        {},
        el("a", { href: c.links?.version, target: "_blank", rel: "noopener", text: "This version" }),
        " · ",
        el("a", { href: c.links?.diff, target: "_blank", rel: "noopener", text: "Difference with the previous version" })
      ),
      el("p", { class: "meta", text: "A case is published only when both AI models agree it is likely manipulation." })
    )
  ));
}

// ---------- Time machine ----------

const monthLabel = (m) => new Date(`${m}-01T00:00:00Z`).toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
const pctText = (a, b) => (b ? `${Math.round((a / b) * 100)}%` : "0%");

// A round scale top (1, 2, 5 × 10^n) so the axis reads 0 / 25 / 50 rather than 0 / 23.5 / 47.
function niceMax(v) {
  const p = 10 ** Math.floor(Math.log10(Math.max(v, 1)));
  return [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].map((k) => k * p).find((k) => k >= v);
}

function renderTimeline(box, rows, cases, onPick) {
  if (!rows.length) {
    box.replaceChildren(el("p", { class: "empty", text: "No timeline data." }));
    return;
  }
  const totalEdits = rows.reduce((s, r) => s + r.edits, 0);
  const totalReverts = rows.reduce((s, r) => s + r.reverts, 0);
  const busiest = rows.reduce((a, b) => (b.edits > a.edits ? b : a));
  const casesByMonth = cases.reduce((m, c) => m.set(String(c.date).slice(0, 7), [...(m.get(String(c.date).slice(0, 7)) || []), c]), new Map());

  // The key figures of the article, each with its unit spelled out.
  const figure = (value, label) => el("div", { class: "tm-stat" }, el("div", { class: "value", text: value }), el("div", { class: "label", text: label }));
  const stats = el(
    "div",
    { class: "tm-stats" },
    figure(fmt(totalEdits), "edits in total"),
    figure(fmt(totalReverts), `reverts (${pctText(totalReverts, totalEdits)} of edits)`),
    figure(fmt(Math.round(totalEdits / rows.length)), "edits per month on average"),
    figure(fmt(busiest.edits), `edits in the busiest month (${monthLabel(busiest.month)})`),
    figure(fmt(cases.length), cases.length === 1 ? "TimeProof case published" : "TimeProof cases published")
  );

  const top = niceMax(Math.max(...rows.map((r) => r.edits), 1));
  const readout = el("p", { class: "tm-readout", "aria-live": "polite" });
  const describe = (r) => {
    const found = casesByMonth.get(r.month) || [];
    readout.replaceChildren(
      el("strong", { text: monthLabel(r.month) }),
      ` · ${fmt(r.edits)} ${r.edits === 1 ? "edit" : "edits"} · ${fmt(r.reverts)} ${r.reverts === 1 ? "revert" : "reverts"}` +
        (r.edits ? ` (${pctText(r.reverts, r.edits)})` : "") +
        (found.length ? ` · ${found.length} TimeProof ${found.length === 1 ? "case" : "cases"}` : "")
    );
  };
  const resetReadout = () =>
    readout.replaceChildren(`${monthLabel(rows[0].month)} – ${monthLabel(rows[rows.length - 1].month)} · hover or tap a month to read its values, click to open the article at that date.`);

  const bars = rows.map((r) => {
    const bar = el("div", { class: "bar", role: "button", tabindex: "0", "aria-label": `${monthLabel(r.month)}: ${r.edits} edits, ${r.reverts} reverts` });
    bar.style.height = `${(r.edits / top) * 100}%`;
    const rev = el("div", { class: "rev" });
    rev.style.height = r.edits ? `${(r.reverts / r.edits) * 100}%` : "0";
    bar.append(rev);
    if (casesByMonth.has(r.month)) bar.append(el("span", { class: "case-mark", title: "TimeProof case" }));
    bar.addEventListener("mouseenter", () => describe(r));
    bar.addEventListener("focus", () => describe(r));
    bar.addEventListener("click", () => {
      describe(r);
      onPick(r.month, bar);
    });
    bar.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        bar.click();
      }
    });
    return bar;
  });

  // Y axis: 0, half and top of the scale, with grid lines behind the bars.
  const yTicks = [top, top / 2, 0];
  const yAxis = el("div", { class: "tm-y" }, yTicks.map((v) => el("span", { text: fmt(v) })));
  const grid = el("div", { class: "tm-grid" }, yTicks.map(() => el("i")));
  const plot = el("div", { class: "timeline" }, grid, ...bars);
  plot.addEventListener("mouseleave", resetReadout);

  // X axis: one label per year, thinned so they never overlap on a phone.
  // Januaries only: the first month is rarely one, and labelling it would crowd the next year.
  let years = rows.map((r, i) => [r.month, i]).filter(([m]) => m.endsWith("-01"));
  if (!years.length) years = [[rows[0].month, 0]];
  const step = Math.ceil(years.length / (window.innerWidth < 600 ? 5 : 12));
  const xAxis = el(
    "div",
    { class: "tm-x" },
    years.filter((_, i) => i % step === 0).map(([m, i]) => {
      const s = el("span", { text: m.slice(0, 4) });
      s.style.left = `${(i / rows.length) * 100}%`;
      return s;
    })
  );

  resetReadout();
  box.replaceChildren(
    stats,
    el(
      "figure",
      { class: "tm-chart" },
      el("p", { class: "tm-axis-title", text: "Edits per month" }),
      el("div", { class: "tm-plot" }, yAxis, el("div", {}, plot, xAxis)),
      el("p", { class: "tm-axis-title tm-x-title", text: "Month of the edit (UTC)" }),
      readout,
      el(
        "figcaption",
        { class: "legend" },
        el("i", { style: "background: var(--brand-text)" }),
        "edits",
        el("i", { style: "background: var(--warning)" }),
        "reverts (an edit that restores an earlier version)",
        el("i", { class: "legend-case" }),
        "month with a published TimeProof case"
      )
    )
  );
}

async function pageTimeMachine() {
  const select = document.getElementById("article");
  const dateInput = document.getElementById("as-of");
  const goBtn = document.getElementById("go");
  const timelineBox = document.getElementById("timeline");
  const textBox = document.getElementById("article-text");

  let articles = [];
  try {
    articles = await api("/api/articles");
  } catch (err) {
    errorBox(textBox, err);
    return;
  }
  select.replaceChildren(...articles.map((a) => el("option", { value: a.page_id, text: `${a.title} (${fmt(a.versions)} versions)` })));
  const wanted = params.get("page_id");
  if (wanted && articles.some((a) => String(a.page_id) === wanted)) select.value = wanted;
  dateInput.value = params.get("as_of") || "2015-06-01";

  async function loadText() {
    const pageId = select.value;
    const asOf = dateInput.value;
    if (!pageId || !asOf) return;
    textBox.replaceChildren(el("p", { class: "empty", text: "Loading…" }));
    try {
      const a = await api(`/api/articles/${pageId}?as_of=${encodeURIComponent(asOf)}`);
      textBox.replaceChildren(
        el("h2", { text: a.title }),
        el(
          "p",
          { class: "meta" },
          `As of ${formatDate(asOf)}: version saved on ${formatDate(a.saved_at)} · `,
          el("a", { href: `https://fi.wikipedia.org/?oldid=${a.rev_id}`, target: "_blank", rel: "noopener", text: "open on Wikipedia" })
        ),
        el("div", { class: "card article-text", text: a.text || "" })
      );
      history.replaceState(null, "", `?page_id=${pageId}&as_of=${asOf}${usingMock && !IS_LOCAL ? "&mock=1" : ""}`);
    } catch (err) {
      errorBox(textBox, err);
    }
  }

  // Published cases are only used to mark their months on the chart: if they fail, the chart still works.
  let allCases = [];
  try {
    allCases = await api("/api/cases");
  } catch (_) {
    allCases = [];
  }

  async function loadTimeline() {
    try {
      const rows = await api(`/api/articles/${select.value}/timeline`);
      const here = allCases.filter((c) => String(c.page_id) === String(select.value));
      renderTimeline(timelineBox, rows, here, (month, bar) => {
        timelineBox.querySelectorAll(".bar.selected").forEach((b) => b.classList.remove("selected"));
        bar.classList.add("selected");
        dateInput.value = `${month}-15`;
        loadText();
      });
    } catch (err) {
      errorBox(timelineBox, err);
    }
  }

  select.addEventListener("change", () => {
    loadTimeline();
    loadText();
  });
  goBtn.addEventListener("click", loadText);
  await loadTimeline();
  await loadText();
}

// ---------- Detection quality ----------

function pct(a, b) {
  return b ? `${Math.round((a / b) * 100)}%` : "–";
}

async function pageQuality() {
  const box = document.getElementById("quality");
  let q;
  try {
    q = await api("/api/quality");
  } catch (err) {
    errorBox(box, err);
    return;
  }
  const notes = q.notes || {};
  const cards = [];
  const card = (value, title, sentence) =>
    cards.push(el("div", { class: "card" }, el("p", { class: "label-small", text: title }), el("div", { class: "value", text: value }), el("p", { text: sentence })));

  // Each block is optional so the page keeps working if a field is added or dropped.
  if (q.synthetic_campaign) {
    const s = q.synthetic_campaign;
    card(
      `${s.caught} / ${s.planted}`,
      "Test campaign caught",
      `We planted ${s.planted} fake manipulative edits in a test copy and ran them through the full pipeline: ${s.caught} were caught (${pct(s.caught, s.planted)}). ` +
        (notes.synthetic_campaign || "These test edits are never shown publicly.")
    );
  }
  if (q.manual_review) {
    const m = q.manual_review;
    card(
      `${m.correct} / ${m.reviewed}`,
      "Flags confirmed by a human",
      `A team member re-read ${m.reviewed} real flagged cases: ${m.correct} were right (${pct(m.correct, m.reviewed)}), ${m.reviewed - m.correct} were false alarms.`
    );
  }
  if (typeof q.downgraded_by_two_model_rule === "number") {
    card(
      fmt(q.downgraded_by_two_model_rule),
      "Cases held back by the two-model rule",
      "Cases where only one of the two AI models saw a problem. They go to human review instead of being published."
    );
  }
  if (typeof q.declared_bots_excluded === "number") {
    card(
      fmt(q.declared_bots_excluded),
      "Official bots excluded",
      "Accounts declared as bots on Finnish Wikipedia do routine maintenance. They are treated as harmless and left out."
    );
  }
  if (typeof q.suspicious_accounts === "number") {
    card(
      fmt(q.suspicious_accounts),
      "Accounts with an unusual pattern",
      "Bot-like rhythm, short-lived or single-topic accounts. A pattern is a hint, not proof, and no account is named."
    );
  }
  const known = new Set(["synthetic_campaign", "manual_review", "downgraded_by_two_model_rule", "declared_bots_excluded", "suspicious_accounts", "notes"]);
  for (const [k, v] of Object.entries(q)) {
    if (!known.has(k) && (typeof v === "number" || typeof v === "string")) card(String(v), k.replaceAll("_", " "), "");
  }
  box.replaceChildren(cards.length ? el("div", { class: "quality-grid" }, cards) : el("p", { class: "empty", text: "No quality figures yet." }));
}

// ---------- Lens: offer the bookmark ----------

async function pageLens() {
  const box = document.getElementById("lens");
  let info;
  try {
    info = await fetchJson("lens.json");
  } catch (err) {
    box.replaceChildren(el("p", { class: "empty", text: "The Lens is not built yet." }));
    return;
  }
  const steps = el(
    "ol",
    { class: "lens-steps" },
    el("li", {}, "Show your bookmarks bar: ", el("strong", { text: "Ctrl + Shift + B" }), " (Cmd + Shift + B on a Mac)."),
    el("li", {}, "Drag the button below onto the bookmarks bar."),
    // Most published cases were later undone on Wikipedia: the example is an article where one is still online.
    el("li", {}, "Open a Finnish Wikipedia article, for example ",
      el("a", { href: "https://fi.wikipedia.org/wiki/Vuosaari", target: "_blank", rel: "noopener", text: "Vuosaari" }),
      ", and click the bookmark. Use the Show buttons in its panel to jump to each case. On an article where a case was later undone, the panel says so."),
    el("li", {}, "Click the bookmark again to turn the Lens off.")
  );
  // A Lens built from sample data must never be offered on the deployed site.
  if (info.mock && !IS_LOCAL) {
    box.replaceChildren(el("p", { class: "empty", text: "The Lens will be available here once real cases are published." }));
    return;
  }
  const button = el("a", { class: "pill lens-button", href: info.href, title: "Drag me to your bookmarks bar", text: "TimeProof Lens" });
  // Clicking it here would only run it on our own site: explain instead.
  button.addEventListener("click", (e) => {
    e.preventDefault();
    alert("Drag this button to your bookmarks bar, then click it on a Finnish Wikipedia article.");
  });
  box.replaceChildren(
    steps,
    el("div", { class: "lens-drag" }, button, el("span", { class: "meta", text: "← Drag me to your bookmarks bar" })),
    info.mock ? el("p", { class: "lens-mock", text: "This Lens is built from sample data: it shows placeholder cases, not real findings." }) : null,
    el("p", { class: "meta", text: `${info.cases} published case${info.cases === 1 ? "" : "s"} included · built ${info.built}. No data is sent anywhere: the cases are stored inside the bookmark and TimeProof never edits Wikipedia.` })
  );
}

// ---------- Boot ----------

const PAGES = { home: pageHome, case: pageCase, timemachine: pageTimeMachine, quality: pageQuality, lens: pageLens };

document.addEventListener("DOMContentLoaded", () => {
  renderLayout();
  const run = PAGES[document.body.dataset.page];
  if (run) run();
});
