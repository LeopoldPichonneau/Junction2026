// TimeProof Lens: runs as a bookmarklet on a fi.wikipedia.org article.
// No network call at all (HTTPS page vs HTTP server = mixed content): build_bookmarklet.py
// inlines the annotations below. Keep this file ASCII-only (\u escapes) so the bookmark stays clean.
(() => {
  const DATA = /*__TIMEPROOF_DATA__*/ null;
  const ID = "timeproof-lens";
  // Colours from web/identity.md.
  const C = { signal: "#b42318", rail: "#2b2d33", railText: "#f2f3f7", muted: "#b9bcc6", brand: "#3f74b0", button: "#2a6fcf" };
  const DOT = " \u00b7 ";

  // A second click removes everything.
  if (document.getElementById(ID)) {
    // The panel itself is tagged "added", so it goes away with the rest.
    document.querySelectorAll("[data-tp-lens]").forEach((n) => {
      if (n.dataset.tpLens === "mark") {
        n.style.outline = n.dataset.tpOutline || "";
        n.style.outlineOffset = "";
        delete n.dataset.tpLens;
      } else n.remove();
    });
    if (window.CSS && CSS.highlights) CSS.highlights.delete("timeproof");
    if (window.__timeproofLensOff) window.__timeproofLensOff.abort(); // drop hover listeners
    return;
  }

  const mw = window.mw;
  if (location.hostname !== "fi.wikipedia.org" || !mw || mw.config.get("wgAction") !== "view") {
    alert("TimeProof Lens works on a Finnish Wikipedia article (fi.wikipedia.org).");
    return;
  }
  if (!DATA) return;

  const pageId = mw.config.get("wgArticleId");
  const cases = DATA.cases.filter((c) => c.page_id === pageId);
  const content = document.getElementById("mw-content-text");

  const el = (tag, style, text) => {
    const n = document.createElement(tag);
    if (style) n.style.cssText = style;
    if (text !== undefined) n.textContent = text; // never innerHTML: texts come from models and Wikipedia
    n.dataset.tpLens = "added";
    return n;
  };
  const fmt = (n) => n.toLocaleString("en-US");
  const readers = (r) => (r === null || r === undefined ? "no reader data (before Jul 2015)" : "\u2248 " + fmt(r) + " readers");
  // Under a day, "0 days" would hide a short but real exposure: count hours instead.
  const duration = (d) => {
    if (d < 1) { const h = Math.max(1, Math.round(d * 24)); return h + (h === 1 ? " hour" : " hours"); }
    const n = Math.round(d); return n + (n === 1 ? " day" : " days");
  };
  const exposure = (c) => (c.online ? "still online after " : "online for ") + duration(c.days) + DOT + readers(c.readers);
  // What the outline means differs: the suspicious text itself (still online), or the original
  // text that an edit had removed and that came back when the edit was undone.
  const story = (c) => {
    if (c.kind === "image") {
      return c.online
        ? "Changed on " + c.date + DOT + "still online after " + duration(c.days)
        : "Changed on " + c.date + DOT + "that version stayed online " + duration(c.days) + ", then was undone";
    }
    return c.side === "added"
      ? "Added on " + c.date + DOT + "still online after " + duration(c.days)
      : "On " + c.date + " an edit removed or rewrote this passage. That version stayed online " + duration(c.days) + ", then this text came back.";
  };
  const norm = (s) => s.replace(/\s+/g, " ").trim().toLowerCase();
  // File names: "Tiedosto:General_Strike_Helsinki_1917.jpg" -> "General strike helsinki 1917.jpg" style key.
  const fileKey = (s) => {
    let f = decodeURIComponent(String(s).split("?")[0].split("#")[0]).replace(/_/g, " ").trim();
    f = f.replace(/^.*\/(?:Tiedosto|File|Kuva|Image):/i, "").replace(/^(?:Tiedosto|File|Kuva|Image):/i, "");
    return f.charAt(0).toUpperCase() + f.slice(1);
  };

  // ---------- Tooltip ----------
  const tip = el(
    "div",
    "position:fixed;z-index:2147483647;max-width:340px;max-height:70vh;overflow-y:auto;background:" + C.rail + ";color:" + C.railText +
      ";font:13px/1.45 system-ui,-apple-system,'Segoe UI',sans-serif;padding:12px 14px;border-radius:6px;" +
      "box-shadow:0 6px 24px rgba(0,0,0,.35);display:none;pointer-events:auto"
  );
  let hideTimer = null;
  tip.addEventListener("mouseenter", () => clearTimeout(hideTimer));
  tip.addEventListener("mouseleave", () => (tip.style.display = "none"));

  // Several cases can sit on the same paragraph or image: one tooltip lists them all.
  function showTip(list, target) {
    clearTimeout(hideTimer);
    tip.replaceChildren();
    const head = el("div", "display:flex;align-items:center;gap:8px;margin-bottom:6px");
    head.append(
      el("span", "background:" + C.brand + ";color:#fff;font:700 11px/1 Georgia,serif;padding:4px 5px;border-radius:3px", "TP"),
      el("span", "font-weight:700", "TimeProof" + (list.length > 1 ? DOT + list.length + " cases here" : ""))
    );
    tip.append(head);
    if (DATA.mock) tip.append(el("div", "color:#ffd84d;font-weight:700;font-size:12px;margin-bottom:4px", "Sample data" + DOT + "not a real finding"));
    list.forEach((c, i) => {
      const block = el("div", i ? "border-top:1px solid rgba(255,255,255,.15);margin-top:10px;padding-top:10px" : "");
      block.append(
        el("div", "font:700 15px/1.3 Georgia,serif;margin-bottom:4px", c.headline),
        el("div", "color:" + C.muted, c.side ? story(c) : (c.kind === "image" ? "Caption changed on " : "Edited on ") + c.date),
        el("div", "font-weight:600;margin:4px 0 8px", c.side ? readers(c.readers) + " saw that version" : exposure(c))
      );
      const link = el("a", "display:inline-block;background:" + C.button + ";color:#fff;font-weight:600;padding:5px 12px;border-radius:999px;text-decoration:none", "Read the evidence");
      link.href = DATA.site.replace(/\/$/, "") + "/case.html?rev_id=" + encodeURIComponent(c.rev_id);
      link.target = "_blank";
      link.rel = "noopener";
      block.append(link);
      tip.append(block);
    });
    tip.style.display = "block";
    const r = target.getBoundingClientRect();
    const top = r.bottom + 8 + tip.offsetHeight > innerHeight ? Math.max(8, r.top - tip.offsetHeight - 8) : r.bottom + 8;
    tip.style.top = top + "px";
    tip.style.left = Math.min(Math.max(8, r.left), innerWidth - tip.offsetWidth - 8) + "px";
  }

  // Each page element is marked once, whatever the number of cases on it, so turning the Lens
  // off restores its original outline. Listeners are removed through one AbortController.
  const off = new AbortController();
  window.__timeproofLensOff = off;
  const byNode = new Map();
  function addCase(node, c) {
    if (!byNode.has(node)) byNode.set(node, []);
    byNode.get(node).push(c);
  }
  function markAll() {
    for (const [node, list] of byNode) {
      node.dataset.tpOutline = node.style.outline;
      node.dataset.tpLens = "mark";
      node.style.outline = "3px solid " + C.signal;
      node.style.outlineOffset = "3px";
      node.addEventListener("mouseenter", () => showTip(list, node), { signal: off.signal });
      node.addEventListener("mouseleave", () => (hideTimer = setTimeout(() => (tip.style.display = "none"), 250)), { signal: off.signal });
    }
  }

  // analysis.jsonl "added" holds the changed words, passage by passage, joined with an ellipsis.
  // Try the whole text, then each passage, then each sentence, longest first; under 6 words a
  // match would be too ambiguous to outline.
  function passages(text) {
    const parts = text.split(/\s*(?:\u2026|\.\.\.)\s*/).map((t) => t.trim()).filter(Boolean);
    const sentences = parts.flatMap((t) => t.split(/(?<=[.!?])\s+/));
    const all = [text, ...parts.sort((a, b) => b.length - a.length), ...sentences.sort((a, b) => b.length - a.length)];
    return [...new Set(all.map(norm))].filter((t) => t.split(" ").length >= 6);
  }

  // ---------- Match cases on the page ----------
  const figures = [...content.querySelectorAll("figure, .thumb, .infobox img")];
  // Passages also live in lists, tables and captions, not only in paragraphs.
  const paragraphs = [...content.querySelectorAll("p, li, dd, td, th, figcaption, blockquote")].map((p) => {
    const clone = p.cloneNode(true);
    clone.querySelectorAll("sup.reference").forEach((s) => s.remove());
    return { p, text: norm(clone.textContent) };
  });
  const ranges = [];
  const found = [];
  const missing = [];

  for (const c of cases) {
    if (c.kind === "image" && c.file) {
      const key = fileKey(c.file);
      const hit = figures.find((f) => {
        const a = f.querySelector("a.mw-file-description, a.image, a[href*=':']");
        const img = f.tagName === "IMG" ? f : f.querySelector("img");
        const names = [];
        if (a) names.push(fileKey(a.getAttribute("href")));
        if (img) names.push(fileKey(img.getAttribute("src").split("/").pop().replace(/^\d+px-/, "")));
        return names.includes(key);
      });
      if (hit) { addCase(hit, c); found.push({ c, node: hit }); continue; }
      // The picture may be gone while its caption text is still there: fall through to the text.
    }
    let hit = null;
    // build_bookmarklet.py now ships ready "needles"; an older build only has the added text.
    const tries = c.needles ? c.needles.map(norm) : passages(c.text || "");
    for (const t of tries) {
      // The smallest element that contains the passage: a list item rather than the whole list.
      const all = paragraphs.filter((x) => x.text.includes(t));
      hit = all.sort((a, b) => a.text.length - b.text.length)[0] || null;
      if (hit) { hit.needle = t; break; }
    }
    if (!hit) { missing.push(c); continue; }
    addCase(hit.p, c);
    found.push({ c, node: hit.p });
    // Exact-passage tint where the browser supports CSS highlights (decoration only).
    if (window.CSS && CSS.highlights && window.Highlight) {
      const walker = document.createTreeWalker(hit.p, NodeFilter.SHOW_TEXT);
      const first = hit.needle.split(" ").slice(0, 4).join(" ");
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const i = norm(n.textContent).indexOf(first);
        if (i >= 0 && !n.parentElement.closest("sup")) {
          const raw = n.textContent.toLowerCase().indexOf(first.split(" ")[0]);
          const range = new Range();
          range.setStart(n, Math.max(0, raw));
          range.setEnd(n, n.textContent.length);
          ranges.push(range);
          break;
        }
      }
    }
  }
  markAll();
  if (ranges.length) {
    CSS.highlights.set("timeproof", new Highlight(...ranges));
    const style = el("style");
    style.textContent = "::highlight(timeproof){background-color:rgba(180,35,24,.14)}";
    document.head.append(style);
  }

  // ---------- Corner panel: what was found ----------
  const panel = el(
    "div",
    "position:fixed;z-index:2147483646;right:16px;bottom:16px;width:340px;max-width:calc(100vw - 32px);max-height:50vh;overflow-y:auto;background:" + C.rail + ";color:" + C.railText +
      ";font:13px/1.45 system-ui,-apple-system,'Segoe UI',sans-serif;padding:12px 14px;border-radius:8px;box-shadow:0 6px 24px rgba(0,0,0,.35)"
  );
  panel.id = ID;
  const top = el("div", "display:flex;align-items:center;gap:8px;margin-bottom:6px");
  top.append(
    el("span", "background:" + C.brand + ";color:#fff;font:700 11px/1 Georgia,serif;padding:4px 5px;border-radius:3px", "TP"),
    el("span", "font-weight:700", "TimeProof Lens")
  );
  panel.append(top);
  if (DATA.mock) panel.append(el("div", "color:#ffd84d;font-weight:700;font-size:12px", "Sample data" + DOT + "not real findings"));
  // The total counts every published case of the article, even those with nothing left to outline.
  const total = Math.max(cases.length, (DATA.totals && DATA.totals[String(pageId)]) || 0);
  panel.append(
    el(
      "div",
      "",
      total
        ? found.length + " of " + total + " TimeProof case" + (total === 1 ? "" : "s") + " on this article located on today's page:"
        : "No TimeProof cases for this article."
    )
  );

  // One row per case on the page: "Show" scrolls to it, flashes it and opens its tooltip.
  // Long articles put cases far apart; this keeps the demo to two clicks.
  const show = (item) => {
    item.node.scrollIntoView({ behavior: "smooth", block: "center" });
    let n = 0;
    const flash = setInterval(() => {
      item.node.style.outlineColor = n % 2 ? C.signal : C.button;
      if (++n > 5) { clearInterval(flash); item.node.style.outlineColor = C.signal; }
    }, 180);
    setTimeout(() => showTip(byNode.get(item.node), item.node), 650);
  };
  for (const item of found) {
    const row = el("div", "display:flex;align-items:center;gap:8px;margin-top:6px");
    row.append(
      el("span", "flex:0 0 auto;font-size:11px;font-weight:700;color:" + C.muted,
        item.c.kind === "image" ? "IMAGE" : item.c.side === "removed" ? "RESTORED" : item.c.side === "added" ? "STILL ONLINE" : "TEXT"),
      el("span", "flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap", item.c.headline)
    );
    const btn = el("button", "flex:0 0 auto;background:" + C.button + ";color:#fff;border:0;border-radius:999px;font:600 12px system-ui,sans-serif;padding:4px 10px;cursor:pointer", "Show");
    btn.type = "button";
    btn.addEventListener("click", () => show(item));
    row.append(btn);
    panel.append(row);
  }
  const notHere = total - found.length;
  if (notHere > 0) {
    const line = el("div", "color:" + C.muted + ";margin-top:8px",
      notHere + " other case" + (notHere === 1 ? " leaves" : "s leave") + " nothing to outline on today's page. ");
    // Every case of the article stays readable on the site, filtered on this article.
    const all = el("a", "color:" + C.railText + ";text-decoration:underline", "See all " + total + " on TimeProof");
    all.href = DATA.site.replace(/\/$/, "") + "/?article=" + encodeURIComponent(mw.config.get("wgTitle"));
    all.target = "_blank";
    all.rel = "noopener";
    line.append(all);
    panel.append(line);
  }
  panel.append(el("div", "color:" + C.muted + ";margin-top:6px;font-size:12px", "Click the bookmark again to turn the Lens off."));
  document.body.append(panel, tip);
})();
