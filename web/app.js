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
  if (readers === null || readers === undefined) return "readers unknown (before Jul 2015)";
  return `≈ ${fmt(readers)} readers`;
}

// Most cases were undone within hours (81 of 97 in less than a day): "0 days" would hide
// a short but real exposure, so count minutes under an hour and hours + minutes under a day.
function durationText(days) {
  if (typeof days !== "number") return "? days";
  const minutes = Math.round(days * 1440);
  if (minutes < 60) return `${Math.max(1, minutes)} min`;
  if (days < 1) {
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return m ? `${h} h ${m} min` : `${h} h`;
  }
  const d = Math.round(days);
  return `${fmt(d)} ${d === 1 ? "day" : "days"}`;
}

// "Hand-checked": a team member found the exact versions where it appeared and disappeared.
// Otherwise the dates are computed automatically from the history: an estimate.
function verifiedBadge(verified) {
  return verified
    ? el("span", { class: "badge ok", title: "A team member checked by hand the versions where it appeared and disappeared.", text: "Hand-checked" })
    : el("span", { class: "badge", title: "Computed automatically from the edit history.", text: "Estimate" });
}

// For calls a page can live without (diff, terms, neighbours): never switch the page to the
// sample data because one of them failed, and never throw.
async function optional(path) {
  try {
    return usingMock ? await api(path) : await fetchJson(path);
  } catch (_) {
    return null;
  }
}

const CONFIDENCE_TIP = "How sure the decider model (Gemini) is that this edit is manipulation. A case is published only if the investigator model (Nemotron) also flagged it.";

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

// An error says what happened and offers a way out, instead of leaving a dead page.
function errorBox(target, err, retry) {
  const again = el("button", { type: "button", class: "pill", text: "Try again" });
  again.addEventListener("click", () => (retry ? retry() : location.reload()));
  target.replaceChildren(
    el("div", { class: "error-box", role: "alert" }, el("p", { class: "error", text: "Could not load data. The server may be busy." }), again)
  );
  target.removeAttribute("aria-busy");
  console.error(err);
}

// Discreet grey bars while data loads (they pulse unless the reader asked for reduced motion).
function skeleton(target) {
  target.setAttribute("aria-busy", "true");
  target.replaceChildren(el("div", { class: "skeleton", "aria-hidden": "true" }, el("i"), el("i"), el("i")), el("span", { class: "sr-only", text: "Loading…" }));
}

// "≈" marks an upper bound: wrap it so its meaning shows on hover, keyboard focus and tap.
const APPROX_TIP = "Upper bound: daily views of the whole article over that period (Wikimedia pageviews, since July 2015).";
function explainApprox(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (n.nodeValue.includes("≈") && !n.parentElement.closest("abbr, option, select")) nodes.push(n);
  }
  for (const n of nodes) {
    const parts = n.nodeValue.split("≈");
    const frag = document.createDocumentFragment();
    parts.forEach((p, i) => {
      if (i) frag.append(el("abbr", { class: "approx", title: APPROX_TIP, "data-tip": APPROX_TIP, tabindex: "0", text: "≈" }));
      frag.append(p);
    });
    n.replaceWith(frag);
  }
}

// Light / dark theme chosen by the reader, remembered when the browser allows it (the site works without).
function currentTheme() {
  const set = document.documentElement.dataset.theme;
  if (set) return set;
  return window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
function themeButton() {
  const b = el("button", { type: "button", class: "theme-toggle" });
  const paint = () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    b.setAttribute("aria-label", `Switch to ${next} theme`);
    b.title = `Switch to ${next} theme`;
    b.innerHTML = next === "dark" // static, trusted markup
      ? `<svg ${ICON_ATTRS}><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>`
      : `<svg ${ICON_ATTRS}><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`;
  };
  b.addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("tp-theme", next); } catch (_) { /* private mode: the choice lasts for this page only */ }
    paint();
  });
  paint();
  return b;
}

// The home page remembers its filters so a case page can link "Back to results" to the same view.
function rememberResults(query) {
  try { sessionStorage.setItem("tp-results", query); } catch (_) { /* storage blocked: plain link instead */ }
}
function resultsLink() {
  try { return "index.html" + (sessionStorage.getItem("tp-results") || ""); } catch (_) { return "index.html"; }
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
      // The accessible name starts with the visible "TP", as WCAG 2.5.3 asks.
      el("a", { class: "brand-mark", href: "index.html", title: "TimeProof home", "aria-label": "TP, TimeProof home", text: "TP" }),
      el(
        "nav",
        { "aria-label": "Main" },
        links.map(([href, label, id]) => {
          const a = el("a", { href, class: id === page ? "active" : null, "aria-current": id === page ? "page" : null });
          a.insertAdjacentHTML("afterbegin", ICONS[id]); // static, trusted markup
          a.append(el("span", { text: label }));
          return a;
        })
      ),
      themeButton()
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

  // Skip link first in the tab order, pointing at the main content.
  const main = document.querySelector("main");
  if (main) {
    main.id = main.id || "main";
    main.setAttribute("tabindex", "-1");
    document.body.prepend(el("a", { class: "skip-link", href: `#${main.id}`, text: "Skip to content" }));
  }
  // Static "Loading…" placeholders become skeletons until the data arrives.
  document.querySelectorAll("p.empty").forEach((p) => {
    if (p.textContent.trim() === "Loading…" && p.parentElement) skeleton(p.parentElement);
  });
}

// ---------- Home: stats + published cases ----------

function caseItem(c) {
  // The list format has no credit by default: a thumbnail only appears when author and license come with it.
  const author = plainText(c.image_author);
  const thumb = c.image_thumb && author && c.image_license
    ? el("figure", {}, el("img", { src: c.image_thumb, alt: "", loading: "lazy", crossorigin: "anonymous", referrerpolicy: "no-referrer" }), el("figcaption", { text: `${author} · ${c.image_license}` }))
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
        el(
          "span",
          { class: "badges" },
          el("span", { class: "tag", text: SIGNAL_LABELS[c.signal_type] || c.signal_type }),
          c.still_online ? el("span", { class: "badge live", text: "Still online" }) : null,
          el("span", { class: "badge", text: durationText(c.days_live) }),
          c.verified ? verifiedBadge(true) : null,
          c.has_compare ? el("span", { class: "badge", title: "This case has a before / after picture slider", text: "Before / after" }) : null
        ),
        el("span", { lang: "fi", text: c.title }),
        el("span", { text: formatDate(c.date) })
      ),
      el("h3", { text: c.headline_en, style: "margin-top: 10px" }),
      el("p", { class: "summary", text: c.summary_en }),
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

  function emptyFilters() {
    const clear = el("button", { type: "button", class: "pill secondary", text: "Clear the filters" });
    clear.addEventListener("click", () => reset.click());
    return el("div", { class: "empty-box" }, el("p", { class: "empty", text: "No case matches these filters." }), clear);
  }

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
    // Sorted by readers, cases without reader data are not "zero readers": they get their own group.
    let blocks = shown.map(caseItem);
    if (sort.value === "readers") {
      const known = shown.filter((c) => typeof c.readers_est === "number");
      const unknown = shown.filter((c) => typeof c.readers_est !== "number");
      if (known.length && unknown.length) {
        blocks = [
          ...known.map(caseItem),
          el("h3", { class: "group-title", text: `Readers unknown (${unknown.length} ${unknown.length === 1 ? "case" : "cases"})` }),
          el("p", { class: "group-note", text: "These edits are older than July 2015, when Wikipedia started publishing daily page views, so nobody can say how many people saw them." }),
          ...unknown.map(caseItem),
        ];
      }
    }
    casesBox.replaceChildren(...(shown.length ? blocks : [emptyFilters()]));
    // Keep the view in the address bar (shareable), without adding history entries.
    const p = new URLSearchParams();
    if (q.value.trim()) p.set("q", q.value.trim());
    for (const [k, s, def] of [["signal", signal, ""], ["article", article, ""], ["status", status, ""], ["from", from, years[0]], ["to", to, years[years.length - 1]], ["sort", sort, "readers"]]) {
      if (s.value !== def) p.set(k, s.value);
    }
    if (params.get("mock") === "1") p.set("mock", "1");
    history.replaceState(null, "", p.toString() ? `?${p}` : location.pathname);
    rememberResults(p.toString() ? `?${p}` : "");
    explainApprox(casesBox);
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
    const stat = (v, l, cls) => el("div", { class: `stat${cls ? ` ${cls}` : ""}` }, el("div", { class: "value", text: fmt(v) }), el("div", { class: "label", text: l }));
    // The funnel: every number comes from /api/stats, nothing is typed in by hand.
    const steps = [
      [s.versions, `versions of ${fmt(s.articles)} articles`],
      [s.candidates, "candidate edits found by rules"],
      [s.analysed, "edits examined by AI"],
      [s.published, "cases published"],
    ].filter(([v]) => typeof v === "number");
    const blocks = [el("ol", { class: "funnel", "aria-label": "From every version to the published cases", style: "grid-column: 1 / -1" }, steps.map(([v, l]) => el("li", {}, stat(v, l))))];
    const unknown = s.readers_unknown_cases ? ` · readers unknown for ${s.readers_unknown_cases} older cases (before July 2015)` : "";
    if (typeof s.readers_unique_est === "number" && s.readers_unique_est > 0) {
      // Overlapping cases on the same article are counted once; still page views, not readers of the passage.
      blocks.push(stat(s.readers_unique_est, `readers exposed (≈, upper bound: page views while a case was online, each moment counted once)${unknown}`, "readers-stat"));
    } else if (typeof s.readers_exposed_est === "number" && s.readers_exposed_est > 0) {
      blocks.push(stat(s.readers_exposed_est, `readers exposed (≈, ${s.readers_note || "upper bound"})${unknown}`, "readers-stat"));
    }
    statsBox.replaceChildren(...blocks);
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
  return el("section", { class: "card" }, el("h2", { class: "label-small", text: title }), ...content);
}

// Alternative text describes the picture (what the investigator saw), never just a file name.
function imageAlt(img, shows) {
  if (shows) return `Image in the article: ${shows}`;
  if (img.caption_new) return `Image in the article, captioned: ${img.caption_new}`;
  return "Image in the article (no description available)";
}

// An image without author and license must not be displayed: returns null in that case.
// The Cloudinary copy (resized, modern format) is used when there is one; the credit stays the same.
function creditedFigure(img, shows, autoUrl) {
  if (!img || !img.thumb_url) return null;
  const author = plainText(img.author);
  if (!author || !img.license) return null;
  return el(
    "figure",
    {},
    el("img", { src: autoUrl || img.thumb_url, alt: imageAlt(img, shows), crossorigin: "anonymous", referrerpolicy: "no-referrer" }),
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
      el("div", {}, el("p", { class: "label-small diff-label minus", text: "Before" }), el("p", { class: "caption-old", lang: "fi", text: img.caption_old || "(none)" })),
      el("div", {}, el("p", { class: "label-small diff-label plus", text: "After" }), el("p", { class: "caption-new", lang: "fi", text: img.caption_new || "(none)" }))
    )
  );
}

// Date with the time when the data has it ("2025-04-14T21:55Z" -> "14 Apr 2025, 21:55 UTC").
function dateTimeText(iso) {
  if (!iso) return "–";
  const t = String(iso).match(/T(\d{2}:\d{2})/);
  return t ? `${formatDate(iso)}, ${t[1]} UTC` : formatDate(iso);
}

// Long unchanged stretches are cut around the change, so the eye goes to what moved.
function trimEqual(text, first, last) {
  const room = 220;
  if (text.length <= room * 2) return text;
  if (first && last) return text;
  if (first) return `… ${text.slice(-room)}`;
  if (last) return `${text.slice(0, room)} …`;
  return `${text.slice(0, room)} … ${text.slice(-room)}`;
}

function diffParagraph(segments) {
  return el("p", { class: "diff-par", lang: "fi" }, segments.map((s, i) => {
    if (s.op === "delete") return el("del", {}, el("span", { class: "sr-only", text: "removed: " }), s.text);
    if (s.op === "insert") return el("ins", {}, el("span", { class: "sr-only", text: "added: " }), s.text);
    return trimEqual(s.text, i === 0, i === segments.length - 1);
  }));
}

function diffSection(c, diff) {
  const translation = c.translation
    ? el(
        "div",
        { class: "translation" },
        el("div", {}, el("p", { class: "label-small diff-label minus", text: "Before (team translation)" }), el("p", { lang: "en", text: c.translation.before_en || "(nothing)" })),
        el("div", {}, el("p", { class: "label-small diff-label plus", text: "After (team translation)" }), el("p", { lang: "en", text: c.translation.after_en || "(nothing)" }))
      )
    : null;

  // The readable text did not change (only an image, a reference or a template did): keep the fragments.
  if (!diff || !diff.text_changed || !diff.paragraphs?.length) {
    if (!c.added && !c.removed && !translation) return null;
    return section(
      "What changed",
      c.added || c.removed
        ? el(
            "div",
            { class: "grid2" },
            el("div", {}, el("p", { class: "label-small diff-label minus", text: "Removed" }), el("div", { class: "diff-removed", lang: "fi", text: c.removed || "(nothing)" })),
            el("div", {}, el("p", { class: "label-small diff-label plus", text: "Added" }), el("div", { class: "diff-added", lang: "fi", text: c.added || "(nothing)" }))
          )
        : null,
      translation
    );
  }

  const SHOWN = 4;
  const pars = diff.paragraphs.map(diffParagraph);
  const box = el("div", {}, pars.slice(0, SHOWN));
  let more = null;
  if (pars.length > SHOWN) {
    more = el("button", { type: "button", class: "pill secondary diff-more", "aria-expanded": "false", text: `Show all ${pars.length} changed paragraphs` });
    more.addEventListener("click", () => {
      box.replaceChildren(...pars);
      more.remove();
    });
  }
  return section(
    "What changed",
    el("p", { class: "meta", text: `Word by word, against the version before (${dateTimeText(diff.parent_saved_at)}). Removed words are struck through, added words underlined. References and images are left out of this text.` }),
    box,
    more,
    translation
  );
}

// From the edit to its end, with the evidence for each step.
function chronology(c, ex) {
  const steps = [
    el("li", { class: "edit" }, el("strong", { text: `Edited on ${dateTimeText(ex.live_from || c.date)}` }),
      el("span", { class: "meta" }, `${SIGNAL_LABELS[c.signal_type] || c.signal_type} · `, el("a", { href: c.links?.diff, target: "_blank", rel: "noopener", text: "the edit on Wikipedia" }))),
    el("li", {}, el("strong", { text: ex.still_online ? `Online for ${durationText(ex.days_live)} so far` : `Online for ${durationText(ex.days_live)}` }),
      el("span", { class: "meta" }, verifiedBadge(ex.verified), readersText(ex.readers_est))),
  ];
  if (ex.still_online) {
    steps.push(el("li", {}, el("strong", { text: "Still online today" }), el("span", { class: "meta", text: "The change is still in the article." })));
  } else {
    const how = ex.ended_by === "revert" ? "Undone by a revert"
      : ex.ended_by === "content removed" ? "The content was removed"
      : "Ended (checked by hand)";
    steps.push(el("li", { class: "end" }, el("strong", { text: `${how} on ${dateTimeText(ex.live_until)}` }),
      ex.ended_by_link ? el("span", { class: "meta" }, el("a", { href: ex.ended_by_link, target: "_blank", rel: "noopener", text: "the edit that ended it" })) : null));
  }
  return section("Chronology", el("ol", { class: "chrono" }, steps));
}

// Before / after slider for a picture case. Both sides are archived pictures rendered by Cloudinary
// at the same size and framing: two different pictures when the edit replaced one, or the same
// picture twice when only the words under it changed.
// The control is a native range input: arrow keys, Home / End and touch work without extra code.
function compareSlider(cmp, title) {
  const before = el("img", { src: cmp.before_url, width: "1200", height: "800", loading: "lazy", crossorigin: "anonymous", referrerpolicy: "no-referrer",
    alt: `Before the edit: the picture in “${title}”${cmp.kind === "replaced" && cmp.before_file ? ` (${cmp.before_file})` : ""}, ${cmp.before_caption ? `with the caption “${cmp.before_caption}”` : "without a caption"}` });
  const after = el("img", { class: "cmp-top", src: cmp.after_url, width: "1200", height: "800", loading: "lazy", crossorigin: "anonymous", referrerpolicy: "no-referrer",
    alt: `After the edit: ${cmp.kind === "replaced" ? `another picture${cmp.after_file ? ` (${cmp.after_file})` : ""}${cmp.before_moved ? " in the same place" : ""}` : "the same picture"}, ${cmp.after_caption ? `with the caption “${cmp.after_caption}”` : "without a caption"}` });
  const handle = el("span", { class: "cmp-handle", "aria-hidden": "true" });
  const tags = [el("span", { class: "cmp-tag left", "aria-hidden": "true", text: "Before" }), el("span", { class: "cmp-tag right", "aria-hidden": "true", text: "After" })];
  const range = el("input", { type: "range", min: "0", max: "100", value: "50", step: "1", id: "cmp-range",
    "aria-label": "Before and after: left of the handle is the picture before the edit, right of it the picture after. Arrow keys move the handle." });
  const stage = el("div", { class: "cmp-stage" }, before, after, handle, tags);
  const set = () => {
    const v = Number(range.value);
    // Left of the handle: before. Right of it: after (the top picture, clipped).
    stage.style.setProperty("--cut", `${v}%`);
    range.setAttribute("aria-valuetext", v === 100 ? "Before the edit only" : v === 0 ? "After the edit only" : `${v}% before, ${100 - v}% after`);
  };
  range.addEventListener("input", set);
  set();
  const caption = (label, cls, fi, en) => el("div", {},
    el("p", { class: `label-small diff-label ${cls}`, text: label }),
    el("p", { class: "cmp-caption", lang: "fi", text: fi || "(none)" }),
    en ? el("p", { class: "meta", lang: "en", text: en }) : null);
  return el(
    "figure",
    { class: "cmp" },
    stage,
    el("div", { class: "cmp-control" }, range),
    el("figcaption", { class: "grid2" },
      caption("Caption before", "minus", cmp.before_caption, cmp.before_caption_en),
      caption("Caption after", "plus", cmp.after_caption, cmp.after_caption_en))
  );
}

// "Visual evidence": what Cloudinary keeps and renders from the exact versions (before / after
// pictures, archived copies of the pictures).
function visualSection(c) {
  const v = c.visual;
  if (!v) return null;
  // One archived copy per picture: two when the edit replaced a picture by another.
  const copies = Array.isArray(v.archive) ? v.archive.filter((a) => a && a.archived_url && plainText(a.author) && a.license) : [];
  if (!v.compare && !copies.length) return null;
  const replaced = v.compare && v.compare.kind === "replaced";
  const shareUrl = `${location.origin}/case/${encodeURIComponent(c.rev_id)}`;
  const note = el("span", { class: "note", "aria-live": "polite" });
  const share = el("button", { type: "button", class: "pill", text: "Share this case" });
  share.addEventListener("click", async () => {
    try {
      if (navigator.share) await navigator.share({ title: c.headline_en, url: shareUrl });
      else { await navigator.clipboard.writeText(shareUrl); note.textContent = "Link copied."; }
    } catch (_) {
      note.textContent = `Copy this link: ${shareUrl}`;
    }
  });
  return section(
    "Visual evidence",
    v.compare ? el("h3", { class: "label-small cmp-title", text: replaced ? (v.compare.before_moved ? "The picture at this place, before and after the edit" : "The picture before and after the edit") : "Same picture, different story" }) : null,
    replaced && v.compare.before_moved
      ? el("p", { class: "meta", text: `The earlier picture${v.compare.before_file ? ` (${v.compare.before_file})` : ""} was not removed: the edit moved it lower in the article and put another one in its place.` })
      : null,
    v.compare ? compareSlider(v.compare, c.title) : null,
    v.compare ? el("p", { class: "meta", text: "Both sides are rendered by Cloudinary from the archived pictures, at the same size and framing. Text from Finnish Wikipedia, CC BY-SA 4.0." }) : null,
    copies.length
      ? el("ul", { class: "archive plain" }, copies.map((a) =>
          el("li", {},
            copies.length > 1 ? `${a.side === "before" ? "Picture before" : "Picture after"}: ` : null,
            el("a", { href: a.archived_url, target: "_blank", rel: "noopener", text: "Archived copy" }),
            " (kept by TimeProof on Cloudinary with its date, author and license)",
            a.original_url ? " · " : null,
            a.original_url ? el("a", { href: a.original_url, target: "_blank", rel: "noopener", text: "Original on Wikimedia Commons" }) : null,
            ` · ${plainText(a.author)}, ${a.license}`)))
      : null,
    el("div", { class: "actions" }, share, note)
  );
}

// Everything an editor needs to check the case on Wikipedia, without TimeProof touching it.
function editorsSection(c, ex) {
  const page = encodeURIComponent(String(c.title).replaceAll(" ", "_"));
  const link = (href, text) => el("a", { href, target: "_blank", rel: "noopener", text });
  const undone = !ex.still_online && ex.ended_by_rev_id ? `, then ended in [[Special:Diff/${ex.ended_by_rev_id}|${ex.ended_by_rev_id}]] on ${formatDate(ex.live_until)}` : ex.still_online ? ", and is still in the article" : "";
  const note =
    `== An edit that may deserve a look ==\n` +
    `The edit [[Special:Diff/${c.rev_id}|${c.rev_id}]] ([https://fi.wikipedia.org/?oldid=${c.rev_id} version]) of ${formatDate(c.date)} ` +
    `stayed online for ${durationText(ex.days_live)}${undone}. ` +
    `It may deserve a look: ${c.headline_en || SIGNAL_LABELS[c.signal_type] || ""}. ` +
    `Evidence: ${location.origin}/case/${c.rev_id} (TimeProof names no account and never edits Wikipedia.) ~~~~`;
  const text = el("textarea", { class: "talk-note", readonly: "readonly", rows: "6", "aria-label": "Talk-page note in wikitext", lang: "en" });
  text.value = note;
  const status = el("span", { class: "note", "aria-live": "polite" });
  const copy = el("button", { type: "button", class: "pill", text: "Copy a talk-page note" });
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(note); status.textContent = "Copied. Paste it on the article's talk page."; }
    catch (_) { text.select(); status.textContent = "Select the text below and copy it."; }
  });
  return section(
    "For Wikipedia editors",
    el("p", {}, link(c.links?.version, "This version"), " · ", link(c.links?.diff, "The edit (diff)"), " · ",
      link(`https://fi.wikipedia.org/wiki/${page}`, "The article today"), " · ",
      link(`https://fi.wikipedia.org/w/index.php?title=${page}&action=history`, "Full history"), " · ",
      link(`https://fi.wikipedia.org/wiki/Keskustelu:${page}`, "Talk page")),
    el("div", { class: "actions" }, copy, status),
    el("details", {}, el("summary", { text: "See the note" }), text),
    el("p", { class: "meta", text: "Nothing is stored by TimeProof and nothing is posted for you: you decide whether to use the note." })
  );
}

// Moving around during a demo: the article before / after, neighbours, other cases on the article.
function navigationSection(c, diff, all) {
  const tm = (asOf) => `timemachine.html?page_id=${encodeURIComponent(c.page_id)}&as_of=${encodeURIComponent(asOf)}`;
  const before = diff?.parent_saved_at;
  const after = diff?.saved_at;
  const links = [];
  if (before) links.push(el("a", { class: "pill secondary", href: tm(before), text: "See the article before this edit" }));
  links.push(el("a", { class: "pill secondary", href: tm(after || c.date), text: "See the article after this edit" }));

  let neighbours = null;
  let others = null;
  if (Array.isArray(all) && all.length) {
    const i = all.findIndex((x) => String(x.rev_id) === String(c.rev_id));
    const go = (x, label) => el("a", { href: `case.html?rev_id=${encodeURIComponent(x.rev_id)}`, rel: label === "Previous case" ? "prev" : "next" }, `${label}: `, el("span", { text: x.headline_en || x.title }));
    if (i >= 0) {
      neighbours = el("p", { class: "case-nav" },
        i > 0 ? go(all[i - 1], "Previous case") : null,
        i > 0 && i < all.length - 1 ? " · " : null,
        i < all.length - 1 ? go(all[i + 1], "Next case") : null);
    }
    const same = all.filter((x) => String(x.page_id) === String(c.page_id) && String(x.rev_id) !== String(c.rev_id));
    if (same.length) {
      others = el("div", {},
        el("h3", { class: "label-small", text: `Other cases on “${c.title}” (${same.length})` }),
        el("ul", { class: "plain" }, same.slice(0, 5).map((x) => el("li", {}, `${formatDate(x.date)} · `, el("a", { href: `case.html?rev_id=${encodeURIComponent(x.rev_id)}`, text: x.headline_en || `Case ${x.rev_id}` })))),
        same.length > 5 ? el("p", {}, el("a", { href: `index.html?article=${encodeURIComponent(c.title)}`, text: `All ${same.length + 1} cases on this article →` })) : null);
    }
  }
  return section("Explore", el("div", { class: "actions" }, links), others, neighbours);
}

async function pageCase() {
  const box = document.getElementById("case");
  const back = document.querySelector("a.back-link");
  if (back) back.href = resultsLink();
  // ?rev= is accepted too, as people shorten links by hand.
  const revId = params.get("rev_id") || params.get("rev");
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
  // Both are optional: without them the page keeps the fragments and drops the neighbours.
  const [diff, all] = await Promise.all([optional(`/api/cases/${revId}/diff`), optional("/api/cases")]);

  document.title = `${c.headline_en} · TimeProof`;
  const ex = c.exposure || {};
  const inv = c.investigator || {};
  const dec = c.decider || {};
  const acc = c.account || {};
  const findings = inv.image_findings;

  // Wrapped in a div so optional blocks (null) are skipped by el() instead of printed as "null".
  const figure = creditedFigure(c.image, findings && findings.what_it_shows, c.image_auto_url);
  const confidence = Math.round((c.confidence || 0) * 100);

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
          el("span", { lang: "fi", text: c.title }),
          el("span", { text: `Edit of ${formatDate(c.date)}` }),
          el("span", { class: "tip", tabindex: "0", title: CONFIDENCE_TIP, "data-tip": CONFIDENCE_TIP, text: `Confidence ${confidence}%` })
        ),
        el("h1", { text: c.headline_en }),
        el(
          "ul",
          { class: "glance", "aria-label": "At a glance" },
          // Each value sits in one span: the glance is a two-column grid.
          el("li", {}, el("strong", { text: "What" }), el("span", { text: `${SIGNAL_LABELS[c.signal_type] || c.signal_type} in “${c.title}”, edit of ${formatDate(c.date)}` })),
          el("li", {}, el("strong", { text: "How long" }),
            el("span", {}, `${ex.still_online ? `still online after ${durationText(ex.days_live)}` : `online for ${durationText(ex.days_live)}`} `, verifiedBadge(ex.verified))),
          el("li", {}, el("strong", { text: "Readers" }), el("span", { text: readersText(ex.readers_est) }))
        ),
        el("p", { class: "lead", text: c.summary_en })
      )
    ),

    el(
      "div",
      { class: "band exposure-band" },
      el("h2", { class: "label-small", text: "Exposure" }),
      el("div", { class: "exposure", text: exposureText(ex.days_live, ex.readers_est, ex.still_online) }),
      el(
        "p",
        { class: "meta" },
        `From ${dateTimeText(ex.live_from)} to ${ex.still_online ? "today (still online)" : dateTimeText(ex.live_until)}. ` +
          (ex.verified ? "Dates checked by hand. " : "Dates computed from the edit history (estimate). ") +
          (typeof ex.readers_est === "number"
            ? "Readers are an upper bound: daily views of the whole article over that period."
            : "Readers unknown: Wikipedia publishes page views only from July 2015.")
      )
    ),

    chronology(c, ex),
    captionBlock(c.image, Boolean(figure)),
    diffSection(c, diff),
    visualSection(c),

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

    section(`Decider · ${dec.model || "unknown model"}`, el("p", { class: "report", text: dec.explanation || "" }),
      el("p", { class: "meta", text: `Confidence ${confidence}%: ${CONFIDENCE_TIP}` })),

    section(
      "Account pattern (no account is named)",
      el("p", { text: ACCOUNT_LABELS[acc.kind] || acc.kind || "Unknown" }),
      acc.reasons && acc.reasons.length ? el("ul", { class: "plain" }, acc.reasons.map((r) => el("li", { text: r }))) : null
    ),

    editorsSection(c, ex),
    navigationSection(c, diff, all)
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
    readout.replaceChildren(`${monthLabel(rows[0].month)} – ${monthLabel(rows[rows.length - 1].month)} · hover or tap a month to read its values, click to open the article at that date. With a keyboard: focus the chart, then use the arrow keys.`);

  // Bars are drawn for the mouse; the keyboard and screen readers use the chart as a single
  // slider (one tab stop instead of hundreds of 3 px targets), plus a table by year below.
  let current = rows.length - 1;
  // Linear by default; the logarithmic scale keeps quiet months visible next to a peak
  // (Suomen sisällissota had about ten times its usual edits in September 2005).
  let log = false;
  const scale = (v) => (log ? Math.log10(1 + v) / Math.log10(1 + top) : v / top);
  const revs = [];
  const bars = rows.map((r, i) => {
    const bar = el("div", { class: "bar", "aria-hidden": "true" });
    const rev = el("div", { class: "rev" });
    revs.push(rev);
    bar.append(rev);
    if (casesByMonth.has(r.month)) bar.append(el("span", { class: "case-mark" }));
    bar.addEventListener("mouseenter", () => describe(r));
    bar.addEventListener("click", () => {
      setCurrent(i);
      onPick(r.month, bar);
    });
    return bar;
  });
  const valueText = (r) => {
    const n = (casesByMonth.get(r.month) || []).length;
    return `${monthLabel(r.month)}: ${r.edits} edits, ${r.reverts} reverts${n ? `, ${n} TimeProof case${n === 1 ? "" : "s"}` : ""}`;
  };
  function setCurrent(i) {
    current = Math.max(0, Math.min(rows.length - 1, i));
    bars.forEach((b, j) => b.classList.toggle("current", j === current));
    plot.setAttribute("aria-valuenow", String(current));
    plot.setAttribute("aria-valuetext", valueText(rows[current]));
    describe(rows[current]);
  }

  // Y axis: 0, half and top of the scale, with grid lines behind the bars.
  const yAxis = el("div", { class: "tm-y" }, el("span"), el("span"), el("span"));
  const grid = el("div", { class: "tm-grid" }, el("i"), el("i"), el("i"));
  function paint() {
    rows.forEach((r, i) => {
      bars[i].style.height = `${scale(r.edits) * 100}%`;
      // The revert share stays a share of the bar on both scales.
      revs[i].style.height = r.edits ? `${(scale(r.reverts) / scale(r.edits)) * 100}%` : "0";
    });
    const middle = log ? Math.round(10 ** (Math.log10(1 + top) / 2) - 1) : top / 2;
    [top, middle, 0].forEach((v, i) => (yAxis.children[i].textContent = fmt(v)));
  }
  paint();
  const logBox = el("input", { type: "checkbox", id: "tm-log" });
  logBox.addEventListener("change", () => { log = logBox.checked; paint(); });
  const logToggle = el("label", { class: "tm-log", for: "tm-log" }, logBox, " Logarithmic scale (keeps quiet months visible next to the busiest ones)");
  const plot = el("div", {
    class: "timeline", tabindex: "0", role: "slider",
    "aria-label": `Edits per month, ${monthLabel(rows[0].month)} to ${monthLabel(rows[rows.length - 1].month)}. Arrow keys change the month, Page Up and Page Down jump a year, Enter opens the article at that month.`,
    "aria-valuemin": "0", "aria-valuemax": String(rows.length - 1),
  }, grid, ...bars);
  plot.addEventListener("mouseleave", () => (document.activeElement === plot ? describe(rows[current]) : resetReadout()));
  plot.addEventListener("focus", () => setCurrent(current));
  plot.addEventListener("keydown", (e) => {
    const moves = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1, PageDown: -12, PageUp: 12 };
    if (e.key in moves) setCurrent(current + moves[e.key]);
    else if (e.key === "Home") setCurrent(0);
    else if (e.key === "End") setCurrent(rows.length - 1);
    else if (e.key === "Enter" || e.key === " ") onPick(rows[current].month, bars[current]);
    else return;
    e.preventDefault();
  });
  plot.setAttribute("aria-valuenow", String(current));
  plot.setAttribute("aria-valuetext", valueText(rows[current]));

  // The same numbers as a table, one row per year, for screen readers and anyone who prefers text.
  const byYear = new Map();
  for (const r of rows) {
    const y = r.month.slice(0, 4);
    const t = byYear.get(y) || { edits: 0, reverts: 0, cases: 0 };
    t.edits += r.edits; t.reverts += r.reverts; t.cases += (casesByMonth.get(r.month) || []).length;
    byYear.set(y, t);
  }
  const table = el(
    "details",
    { class: "tm-table" },
    el("summary", { text: "Show the numbers as a table (per year)" }),
    el(
      "table",
      {},
      el("caption", { class: "sr-only", text: "Edits, reverts and TimeProof cases per year" }),
      el("thead", {}, el("tr", {}, ["Year", "Edits", "Reverts", "TimeProof cases"].map((h) => el("th", { scope: "col", text: h })))),
      el("tbody", {}, [...byYear].map(([y, t]) => el("tr", {}, el("th", { scope: "row", text: y }), el("td", { text: fmt(t.edits) }), el("td", { text: fmt(t.reverts) }), el("td", { text: fmt(t.cases) }))))
    )
  );

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

  // The red marks are mouse-sized: the same cases as plain links, readable with any device.
  const caseList = cases.length
    ? el(
        "div",
        { class: "tm-cases" },
        el("h2", { class: "label-small", text: `TimeProof ${cases.length === 1 ? "case" : "cases"} on this article` }),
        el("ul", { class: "plain" }, [...cases].sort((a, b) => String(a.date).localeCompare(String(b.date))).map((c) =>
          el("li", {}, el("span", { class: "meta-inline", text: `${formatDate(c.date)} · ${SIGNAL_LABELS[c.signal_type] || c.signal_type} · ` }),
            el("a", { href: `case.html?rev_id=${encodeURIComponent(c.rev_id)}`, text: c.headline_en || `Case ${c.rev_id}` }))))
      )
    : null;

  resetReadout();
  box.replaceChildren(
    stats,
    el(
      "figure",
      { class: "tm-chart" },
      logToggle,
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
      ),
      table
    ),
    caseList
  );
}

// "How Wikipedia names the 1918 war": share of each kind of name, month by month
// (data/exchange/term-timeline.json, made by analysis/term_timeline.py, served by /api/terms).
const TERM_GROUPS = [
  ["neutral", "neutral", "Neutral names (sisällissota, kansalaissota, veljessota)"],
  ["white_framing", "white", "White side's names (vapaussota, punakapina)"],
  ["red_framing", "red", "Red side's name (luokkasota)"],
];

function renderTerms(box, data) {
  const views = [
    ["article", data.article?.title ? `“${data.article.title}”` : "The main article", data.article?.months || []],
    ["corpus", `All ${fmt(data.corpus?.articles)} articles`, data.corpus?.months || []],
  ].filter(([, , months]) => months.length);
  if (!views.length) return;
  box.hidden = false;
  const NS = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs = {}, text) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const W = 800, H = 240, L = 44, R = 12, T = 12, B = 28;
  const plotBox = el("div");
  const summary = el("p", { class: "tm-readout", "aria-live": "polite" });
  const tableBox = el("div");
  const share = (m, key) => {
    const total = TERM_GROUPS.reduce((s, [k]) => s + (m.groups?.[k] || 0), 0);
    return total ? (m.groups[key] || 0) / total : null;
  };

  function draw(months, label) {
    const x = (i) => L + (i / Math.max(1, months.length - 1)) * (W - L - R);
    const y = (v) => T + (1 - v) * (H - T - B);
    const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Share of each kind of name for the 1918 war, ${label}, ${monthLabel(months[0].month)} to ${monthLabel(months[months.length - 1].month)}` });
    for (const v of [0, 0.5, 1]) {
      root.append(svg("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "axis" }));
      root.append(svg("text", { x: L - 8, y: y(v) + 4, "text-anchor": "end", class: "axis-label" }, `${v * 100}%`));
    }
    months.forEach((m, i) => {
      if (m.month.endsWith("-01") && Number(m.month.slice(0, 4)) % (window.innerWidth < 600 ? 6 : 3) === 0) {
        root.append(svg("text", { x: x(i), y: H - 8, "text-anchor": "middle", class: "axis-label" }, m.month.slice(0, 4)));
      }
    });
    for (const [key, cls] of TERM_GROUPS) {
      let d = "";
      months.forEach((m, i) => {
        const v = share(m, key);
        if (v === null) return;
        d += `${d ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
      });
      root.append(svg("path", { d, class: `line ${cls}` }));
    }
    plotBox.replaceChildren(root);
    const last = months[months.length - 1];
    summary.textContent = `${monthLabel(last.month)}: ` + TERM_GROUPS.map(([k, , name]) => `${pctText(last.groups?.[k] || 0, TERM_GROUPS.reduce((s, [g]) => s + (last.groups?.[g] || 0), 0))} ${name.split(" (")[0].toLowerCase()}`).join(" · ");
    // One row per year (state in January), for screen readers and anyone who prefers numbers.
    const rows = months.filter((m) => m.month.endsWith("-01"));
    tableBox.replaceChildren(el("details", { class: "tm-table" }, el("summary", { text: "Show the numbers as a table (January of each year)" }),
      el("table", {}, el("caption", { class: "sr-only", text: `Mentions of each kind of name, ${label}` }),
        el("thead", {}, el("tr", {}, ["Year", "Neutral", "White side", "Red side"].map((h) => el("th", { scope: "col", text: h })))),
        el("tbody", {}, rows.map((m) => el("tr", {}, el("th", { scope: "row", text: m.month.slice(0, 4) }),
          TERM_GROUPS.map(([k]) => el("td", { text: fmt(m.groups?.[k] || 0) }))))))));
  }

  const buttons = views.map(([id, label, months], i) => {
    const b = el("button", { type: "button", class: "pill secondary", "aria-pressed": String(i === 0), text: label });
    b.addEventListener("click", () => {
      buttons.forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
      draw(months, label);
    });
    return b;
  });
  box.replaceChildren(
    el("h2", { text: "How Wikipedia names the 1918 war" }),
    el("p", { class: "meta", text: "Each month, the share of each name in the text as it stood at the end of that month. The name chosen tells which side the text takes." }),
    el("div", { class: "switch", role: "group", "aria-label": "Which articles" }, buttons),
    el("figure", { class: "tm-chart" }, plotBox, summary,
      el("figcaption", { class: "legend" }, TERM_GROUPS.flatMap(([, cls, name]) => [el("i", { class: cls }), name]))),
    tableBox
  );
  draw(views[0][2], views[0][1]);
}

// Search box for the article (WAI-ARIA combobox): the server returns the 20 most edited
// matches, so the page never loads the 19,742 titles at once.
function articleSearch(input, list, onChoose) {
  let timer = null;
  let asked = 0;          // only the answer to the latest keystroke is shown
  let items = [];
  let active = -1;

  const close = () => {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  };
  const highlight = (i) => {
    active = i;
    [...list.children].forEach((li, j) => li.setAttribute("aria-selected", j === i ? "true" : "false"));
    if (i >= 0 && list.children[i]) {
      input.setAttribute("aria-activedescendant", list.children[i].id);
      list.children[i].scrollIntoView({ block: "nearest" });
    } else input.removeAttribute("aria-activedescendant");
  };
  const choose = (a) => {
    close();
    input.value = a.title;
    onChoose(a);
  };
  const show = (found, query) => {
    items = found;
    if (!found.length) {
      list.replaceChildren(el("li", { class: "combo-empty", role: "option", "aria-disabled": "true", id: "article-none", text: `No article title contains “${query}”, in Finnish or in English.` }));
    } else {
      list.replaceChildren(...found.map((a, i) => {
        const li = el("li", { role: "option", id: `article-opt-${i}`, "aria-selected": "false" },
          // The English title is the one of the linked English Wikipedia article, when there is one.
          el("span", {}, el("span", { lang: "fi", text: a.title }),
            a.title_en && a.title_en !== a.title ? el("span", { class: "combo-en", lang: "en", text: a.title_en }) : null),
          el("span", { class: "combo-count", text: `${fmt(a.versions)} versions` }));
        // mousedown, not click: it fires before the input loses focus.
        li.addEventListener("mousedown", (e) => { e.preventDefault(); choose(a); });
        return li;
      }));
    }
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    active = -1;
  };
  async function search(query) {
    const ticket = ++asked;
    let found;
    try {
      found = await api(`/api/articles?q=${encodeURIComponent(query)}&limit=20`);
    } catch (_) {
      return;
    }
    if (ticket !== asked) return;
    // The local sample files ignore ?q=, so filter them here. The real API already matched
    // (ignoring accents too: "sisallis" finds "sisällissota"), so its answer is kept as is.
    const low = query.toLowerCase();
    show(usingMock ? found.filter((a) => `${a.title} ${a.title_en || ""}`.toLowerCase().includes(low)).slice(0, 20) : found, query);
  }

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const query = input.value.trim();
    if (query.length < 2) { asked++; close(); return; }
    timer = setTimeout(() => search(query), 200);
  });
  input.addEventListener("keydown", (e) => {
    const open = !list.hidden && items.length;
    if (e.key === "ArrowDown" && open) highlight(Math.min(active + 1, items.length - 1));
    else if (e.key === "ArrowUp" && open) highlight(Math.max(active - 1, 0));
    else if (e.key === "Enter" && open) choose(items[active >= 0 ? active : 0]);
    else if (e.key === "Escape" && !list.hidden) close();
    else return;
    e.preventDefault();
  });
  input.addEventListener("blur", () => setTimeout(close, 100));
}

async function pageTimeMachine() {
  const input = document.getElementById("article-q");
  const list = document.getElementById("article-list");
  const popularBox = document.getElementById("popular");
  const dateInput = document.getElementById("as-of");
  const goBtn = document.getElementById("go");
  const timelineBox = document.getElementById("timeline");
  const termsBox = document.getElementById("terms");
  const textBox = document.getElementById("article-text");

  // Most edited articles, as one-click shortcuts.
  let popular = [];
  try {
    popular = (await api("/api/articles?limit=8")).slice(0, 8);
  } catch (err) {
    errorBox(textBox, err);
    return;
  }

  // No article is opened by default: the reader chooses one (a link can carry ?page_id=).
  let pageId = /^\d+$/.test(params.get("page_id") || "") ? params.get("page_id") : "";
  // A link from a case carries the exact second of the edit (as_of=2019-09-27T21:53:44Z);
  // the date field only holds a day, so that exact time is used until the date is changed.
  let exactAsOf = /T/.test(params.get("as_of") || "") ? params.get("as_of") : null;
  dateInput.value = (params.get("as_of") || "2015-06-01").slice(0, 10);

  async function loadText() {
    const asOf = exactAsOf && exactAsOf.slice(0, 10) === dateInput.value ? exactAsOf : dateInput.value;
    if (!pageId || !asOf) return;
    textBox.replaceChildren(el("p", { class: "empty", text: "Loading…" }));
    try {
      const a = await api(`/api/articles/${pageId}?as_of=${encodeURIComponent(asOf)}`);
      input.value = a.title;
      const wikiVersion = `https://fi.wikipedia.org/w/index.php?oldid=${a.rev_id}`;
      textBox.replaceChildren(
        el("h2", { lang: "fi", text: a.title }),
        el(
          "p",
          { class: "meta" },
          `As of ${formatDate(asOf)}${asOf.includes("T") ? `, ${asOf.slice(11, 16)} UTC` : ""}: version saved on ${formatDate(a.saved_at)} · `,
          el("a", { href: `https://fi.wikipedia.org/?oldid=${a.rev_id}`, target: "_blank", rel: "noopener", text: "open on Wikipedia" })
        ),
        // The text is Finnish. English is one click away, and labelled for what it is.
        el(
          "p",
          { class: "meta in-english" },
          el("strong", { text: "In English:" }),
          el("a", { href: `https://translate.google.com/translate?sl=fi&tl=en&u=${encodeURIComponent(wikiVersion)}`, target: "_blank", rel: "noopener", text: "this exact version, machine-translated by Google Translate" }),
          a.title_en
            ? el("span", {}, "or the English Wikipedia article ",
                el("a", { href: `https://en.wikipedia.org/wiki/${encodeURIComponent(a.title_en.replaceAll(" ", "_"))}`, target: "_blank", rel: "noopener", lang: "en", text: a.title_en }),
                " (written separately: not a translation)")
            : null
        ),
        el("div", { class: "card article-text", lang: "fi", text: a.text || "" })
      );
      history.replaceState(null, "", `?page_id=${pageId}&as_of=${encodeURIComponent(asOf)}${usingMock && !IS_LOCAL ? "&mock=1" : ""}`);
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
      const rows = await api(`/api/articles/${pageId}/timeline`);
      const here = allCases.filter((c) => String(c.page_id) === String(pageId));
      renderTimeline(timelineBox, rows, here, (month, bar) => {
        timelineBox.querySelectorAll(".bar.selected").forEach((b) => b.classList.remove("selected"));
        bar.classList.add("selected");
        exactAsOf = null;
        dateInput.value = `${month}-15`;
        loadText();
      });
    } catch (err) {
      errorBox(timelineBox, err);
    }
  }

  // "How Wikipedia names the 1918 war" belongs to the article it was measured on (the article
  // about that war): it is not shown under any other article.
  const termsAsked = optional("/api/terms");
  let termsDrawn = false;
  async function showTerms() {
    const terms = await termsAsked;
    const here = terms && terms.article && String(terms.article.page_id) === String(pageId);
    if (here && !termsDrawn) {
      renderTerms(termsBox, terms);
      termsDrawn = true;
    }
    termsBox.hidden = !here;
  }

  async function open(id) {
    pageId = String(id);
    popularBox.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.id === pageId)));
    // The chart and the 1918 names are drawn before the text arrives, so nothing jumps under the reader's eyes.
    await loadTimeline();
    await showTerms();
    await loadText();
  }

  popularBox.replaceChildren(
    el("span", { class: "label-small", text: "Popular" }),
    ...popular.map((a) => {
      const b = el("button", { type: "button", class: "pill secondary", "data-id": a.page_id, "aria-pressed": String(String(a.page_id) === pageId), lang: "fi", text: a.title,
        title: a.title_en && a.title_en !== a.title ? `In English: ${a.title_en}` : null });
      b.addEventListener("click", () => open(a.page_id));
      return b;
    })
  );
  articleSearch(input, list, (a) => open(a.page_id));
  goBtn.addEventListener("click", () => { exactAsOf = null; loadText(); });
  dateInput.addEventListener("change", () => { exactAsOf = null; });

  if (pageId) {
    await open(pageId);
  } else {
    timelineBox.removeAttribute("aria-busy");
    timelineBox.replaceChildren(el("p", { class: "empty tm-empty", text: "Search an article above, in Finnish or in English, or pick one of the most edited ones." }));
  }
}

// ---------- Detection quality ----------

function pct(a, b) {
  return b ? `${Math.round((a / b) * 100)}%` : "–";
}

// The pipeline as a figure: horizontal on a wide screen, vertical on a phone so the text stays readable.
function pipelineFigure(steps) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs = {}, text) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const vertical = window.innerWidth < 640;
  const W = 184, H = vertical ? 88 : 104, GAP = vertical ? 24 : 30;
  const width = vertical ? 300 : steps.length * W + (steps.length - 1) * GAP;
  const height = vertical ? steps.length * H + (steps.length - 1) * GAP : H;
  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-labelledby": "pipe-title pipe-desc" });
  root.append(svg("title", { id: "pipe-title" }, "How a case gets published"));
  root.append(svg("desc", { id: "pipe-desc" }, steps.map((s) => `${s.title}: ${s.sub}`).join(". ")));
  const defs = svg("defs");
  const marker = svg("marker", { id: "pipe-arrow", viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse" });
  marker.append(svg("path", { d: "M0 0 L10 5 L0 10 z", class: "arrow-head" }));
  defs.append(marker);
  root.append(defs);
  steps.forEach((s, i) => {
    const x = vertical ? 0 : i * (W + GAP);
    const y = vertical ? i * (H + GAP) : 0;
    const w = vertical ? width : W;
    root.append(svg("rect", { x, y, width: w, height: H, rx: "4", class: `box${s.key ? " key" : ""}` }));
    root.append(svg("text", { x: x + 12, y: y + 30 }, s.title));
    s.sub.split("\n").forEach((line, j) => root.append(svg("text", { x: x + 12, y: y + 52 + j * 16, class: "sub" }, line)));
    if (i < steps.length - 1) {
      const d = vertical
        ? `M${width / 2} ${y + H + 4} V${y + H + GAP - 4}`
        : `M${x + W + 4} ${H / 2} H${x + W + GAP - 4}`;
      root.append(svg("path", { d, class: "arrow", "marker-end": "url(#pipe-arrow)" }));
    }
  });
  return el("figure", { class: "pipeline" }, root);
}

const pctOf = (share) => (typeof share === "number" ? `${Math.round(share * 100)}%` : "–");

async function pageQuality() {
  const box = document.getElementById("quality");
  let q;
  try {
    q = await api("/api/quality");
  } catch (err) {
    errorBox(box, err);
    return;
  }
  const s = (await optional("/api/stats")) || {};
  const det = q.details || {};
  const dec = det.decisions || {};
  const notes = q.notes || {};
  const cards = [];
  const card = (value, title, sentence) =>
    cards.push(el("section", { class: "card" }, el("h2", { class: "label-small", text: title }), el("div", { class: "value", text: value }), el("p", { text: sentence })));

  // Every number of the figure comes from the API; a missing one is shown as "–".
  const n = (v) => (typeof v === "number" ? fmt(v) : "–");
  const steps = [
    { title: "Rules", sub: `scan ${n(s.versions)} versions\n→ ${n(s.candidates)} candidates` },
    { title: "Nemotron investigates", sub: `${n(s.analysed ?? ([dec.flag, dec.human_review, dec.dismiss].every(Number.isFinite) ? dec.flag + dec.human_review + dec.dismiss : undefined))} edits examined\nimages, sources, words` },
    { title: "Gemini decides", sub: `flag, dismiss or\nask a human\n${n(dec.dismiss)} dismissed` },
    { title: "Two-model rule", sub: "publish only if\nboth models agree", key: true },
    { title: "Published / human", sub: `${n(dec.flag ?? det.published)} published\n${n(dec.human_review)} sent to a human` },
  ];

  // Each block is optional so the page keeps working if a field is added or dropped.
  if (q.synthetic_campaign) {
    const t = q.synthetic_campaign;
    card(
      `${t.caught} / ${t.planted}`,
      "Test campaign caught",
      `We planted ${t.planted} fake manipulative edits in a test copy and ran them through the full pipeline: ${t.caught} were caught (${pct(t.caught, t.planted)}). These test edits are never shown publicly.`
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
    card(fmt(q.downgraded_by_two_model_rule), "Cases held back by the two-model rule",
      notes.downgraded_by_two_model_rule || "Cases where only one of the two AI models saw a problem. They go to human review instead of being published.");
  }
  if (typeof q.declared_bots_excluded === "number") {
    card(fmt(q.declared_bots_excluded), "Official bots excluded",
      "Accounts declared as bots on Finnish Wikipedia do routine maintenance. They are treated as harmless and left out.");
  }
  if (typeof q.suspicious_accounts === "number") {
    card(fmt(q.suspicious_accounts), "Accounts with an unusual pattern",
      "Bot-like rhythm, short-lived or single-topic accounts. A pattern is a hint, not proof, and no account is named.");
  }
  const known = new Set(["synthetic_campaign", "manual_review", "downgraded_by_two_model_rule", "declared_bots_excluded", "suspicious_accounts", "notes", "long_tail", "repeat_accounts", "time_online", "details"]);
  for (const [k, v] of Object.entries(q)) {
    if (!known.has(k) && (typeof v === "number" || typeof v === "string")) card(String(v), k.replaceAll("_", " "), "");
  }

  const blocks = [section("How a case gets published", pipelineFigure(steps),
    el("p", { class: "meta", text: "Nemotron (the investigator) and Gemini (the decider) are two different AI models. When they disagree, nothing is published: a human decides." }))];
  blocks.push(cards.length ? el("div", { class: "quality-grid" }, cards) : el("p", { class: "empty", text: "No quality figures yet." }));

  // Rarely watched articles: suspicious edits stay online longer.
  const lt = q.long_tail;
  if (lt && Array.isArray(lt.buckets) && lt.buckets.length) {
    blocks.push(section(
      "Less watched articles keep suspicious edits longer",
      el("div", { class: "table-scroll" }, el("table", { class: "q-table" },
        el("caption", { class: "sr-only", text: "Suspicious edits by how often the article is edited" }),
        el("thead", {}, el("tr", {}, ["Articles", "Suspicious edits", "Half were removed within", "Online > 1 day", "Online > 30 days", "Still online"].map((h) => el("th", { scope: "col", text: h })))),
        el("tbody", {}, lt.buckets.map((b) => el("tr", {},
          el("th", { scope: "row", text: b.bucket }),
          el("td", { text: fmt(b.suspicious_edits) }),
          el("td", { text: durationText(b.median_days_online) }),
          el("td", { text: pctOf(b.share_online_over_1_day) }),
          el("td", { text: pctOf(b.share_online_over_30_days) }),
          el("td", { text: fmt(b.still_online) })))))),
      ...lt.buckets.filter((b) => b.sentences?.caveat).map((b) => el("p", { class: "meta", text: `${b.bucket}: ${b.sentences.caveat}` })),
      lt.definition ? el("p", { class: "meta", text: lt.definition }) : null
    ));
  }

  const ra = q.repeat_accounts;
  if (ra && ra.sentences) {
    blocks.push(section(
      "Accounts that come back",
      el("ul", { class: "plain" }, Object.values(ra.sentences).map((t) => el("li", { text: t }))),
      ra.definition ? el("p", { class: "meta", text: ra.definition }) : null
    ));
  }

  const to = q.time_online;
  if (to && (to.sentence || typeof to.compared === "number")) {
    blocks.push(section(
      "How reliable the time online is",
      el("p", { text: to.sentence || `Two methods agree within a day on ${to.agree_within_1_day} of ${to.compared} cases.` }),
      typeof to.checked_by_hand === "number"
        ? el("p", { class: "meta", text: `${to.checked_by_hand} cases were checked by hand, version by version. On published cases they carry the “Hand-checked” badge; the others say “Estimate”.` })
        : null
    ));
  }

  box.replaceChildren(...blocks);
}

// ---------- Lens: offer the bookmark ----------

async function pageLens() {
  const box = document.getElementById("lens");
  let info;
  try {
    // The bookmark is rebuilt from time to time: never offer a cached, older copy.
    info = await fetchJson(`lens.json?t=${Date.now()}`);
  } catch (err) {
    box.replaceChildren(el("p", { class: "empty", text: "The Lens is not built yet." }));
    return;
  }
  const wiki = (title) => el("a", { href: `https://fi.wikipedia.org/wiki/${encodeURIComponent(title.replaceAll(" ", "_"))}`, target: "_blank", rel: "noopener", lang: "fi", text: title });
  const steps = el(
    "ol",
    { class: "lens-steps" },
    el("li", {}, "Show your bookmarks bar (", el("strong", { text: "Ctrl + Shift + B" }), ", or Cmd + Shift + B on a Mac) and drag the button below onto it."),
    el("li", {}, "Open a Finnish Wikipedia article, for example ", wiki("Suomen sisällissota"), " or ", wiki("Carl Gustaf Emil Mannerheim"),
      ", and click the bookmark: the passages of TimeProof cases are outlined, and its panel lists them."),
    el("li", {}, "Click the bookmark again to turn the Lens off.")
  );
  // The Lens can only outline what is still on today's page: say how many cases that is.
  const stats = await optional("/api/stats");
  const coverage = stats && typeof stats.published === "number"
    ? `${info.cases} of ${stats.published} published cases can be shown on today's pages: the others were rewritten since, or are too short to find reliably. All of them are on this site.`
    : `${info.cases} published case${info.cases === 1 ? "" : "s"} included.`;
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
    info.mock ? el("p", { class: "lens-mock", text: "This Lens is built from sample data: it shows placeholder cases, not real findings." }) : "",
    el("p", { class: "lens-coverage", text: coverage }),
    el("p", { class: "meta", text: `Built ${info.built}. No data is sent anywhere: the cases are stored inside the bookmark and TimeProof never edits Wikipedia.` })
  );
}

// ---------- Boot ----------

const PAGES = { home: pageHome, case: pageCase, timemachine: pageTimeMachine, quality: pageQuality, lens: pageLens };

document.addEventListener("DOMContentLoaded", () => {
  renderLayout();
  const run = PAGES[document.body.dataset.page];
  Promise.resolve(run ? run() : null).finally(() => {
    document.querySelectorAll("[aria-busy]").forEach((n) => n.removeAttribute("aria-busy"));
    const main = document.querySelector("main");
    if (main) explainApprox(main);
  });
});
