# TimeProof — Visual identity

Inspired by: "Wikipedia concept of web site. With mobile version" by M ART (Behance). **Principles only**: a saturated blue hero band with a large white serif headline, a slim dark side rail for navigation, two-tone section headings (second word in the brand colour), alternating text/image rows, small pill buttons, a light grey footer bar, serif for reading. Nothing copied: no logo or "W" tile, no section names, no photos, no category-icon grid, and the blue is the reference's soft hero blue `#447cbb` (chosen by the team), which is not Wikimedia's interface blue (`#36c` / `#0645ad`).

**TimeProof must never look like a Wikimedia product.** It is independent evidence about Wikipedia. Never use the Wikipedia wordmark, the puzzle globe, a "W" tile, or "wikipedia" as a title; the TimeProof "TP" mark and wordmark are always visible.

Mood in 3 words: **clear, confident, evidential.**

## Colour

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` / `--surface` | `#ffffff` | `#121317` / `#1a1b21` | Page, cards |
| `--surface-2` | `#f2f3f7` | `#1d1f26` | Quiet rows, footer bar |
| `--rail` / `--rail-text` / `--rail-muted` | `#2b2d33` / `#f2f3f7` / `#b9bcc6` | `#0b0c0f` / `#f2f3f7` / `#a3a7b3` | Side rail |
| `--brand` | `#447cbb` | `#447cbb` | **Fill only**, always under white text: hero band, pill buttons, case hero, buttons. White on it 4.3:1, so text on it is white (never tinted), large or semibold |
| `--button` / `--button-hover` | `#3687eb` / `#2a74d4` | same | Pill buttons (bright reference blue, white text 3.6:1, kept semibold) |
| `--brand-text` | `#3687eb` | `#3687eb` | Blue **text or marks on the page background**: two-tone words, timeline bars, active rail marker (≥ 4.5:1 in both themes) |
| `--brand-strong` / `--brand-soft` | `#3a6ca6` / `#e8f0f9` | `#3a6ca6` / `#1b2636` | Hover; tinted backgrounds |
| `--on-brand` / `--on-brand-muted` | `#ffffff` / `#ffffff` | `#ffffff` / `#ffffff` | Text on the blue band |
| `--line` | `#e1e3ea` | `#2c2e37` | Hairlines |
| `--text` / `--text-2` | `#1c1d22` / `#565965` | `#eef0f5` / `#a8abb7` | Text (secondary ≥ 4.5:1, never lighter) |
| `--link` | `#2f5f99` | `#7fb0ec` | Inline links |
| `--signal` | `#b42318` | `#ff7466` | **Evidence only**: flags, highlights, the Lens outline |
| `--added` / `--added-text` | `#e6f2ea` / `#1d5c34` | `#16301f` / `#9fd8b0` | Diff: added |
| `--removed` / `--removed-text` | `#fbeae8` / `#8f1c13` | `#3a1d1a` / `#ffb3aa` | Diff: removed |
| (mock badge) | `--rail` + `--rail-text` | same | "Sample data" corner badge, only on local mock pages |

**Lens (bookmarklet)**: it cannot load this file, so `lens/build_bookmarklet.py` inlines these hex values: outline `#b42318` (3px), tooltip background `#2b2d33` with text `#f2f3f7`, a `#447cbb` "TP" badge and the TimeProof wordmark in the tooltip so it never looks like native Wikipedia UI.

## Typography

- **Serif: Source Serif 4** (Google Fonts), 400, 600, 700, plus 400 italic. Headlines, reading text, case titles, big numbers.
- **Sans: Inter** (Google Fonts), 400, 500, 600, 700. Rail, labels, meta, buttons.
- Numbers: `font-variant-numeric: tabular-nums`.

| Role | Font | Size / line-height |
|---|---|---|
| Display (blue hero) | Source Serif 4 700 | clamp(34px, 6vw, 60px) / 1.15 |
| h1 | Source Serif 4 700 | clamp(28px, 4.5vw, 42px) / 1.15 |
| h2 (two-tone) | Source Serif 4 700 | 28px / 1.2 |
| h3 | Source Serif 4 700 | 20px / 1.3 |
| Reading text | Source Serif 4 400 | 18px / 1.6 |
| Body UI | Inter 400 | 16px / 1.6 |
| Small / meta | Inter 400 | 13px |
| Label | Inter 600, uppercase, +0.08em | 11px |

## Spacing & shape

- Base unit 8px; rail 88px wide (desktop ≥ 900px), becomes a top bar below; container 1040px; gutter 16px; section padding 56px.
- Radius: 4px for cards and images; pill (999px) for buttons and tags.
- Shadow: one soft recipe, for hover and floating elements only.

## Components

- **Rail**: dark vertical bar on the left with the "TP" mark (ultramarine square, white serif letters) and nav items as icon + small text label. Active item: white text and a brand-coloured left bar.
- **Hero band**: full-width ultramarine block, large white serif headline, white text, figures in white serif.
- **Two-tone heading**: `Published <span>cases</span>`: first word in text colour, second word in `--brand-text`.
- **Pill button**: small ultramarine pill, white Inter 600 ("Read the evidence"). Secondary: outline pill.
- **Row**: serif title, sans summary, meta, pill button; hairline between rows. With a credited image, image and text alternate sides; without, the row stands alone (it must look complete without an image).
- **Tag**: uppercase Inter pill; outline by default, filled `--signal` only for a flagged signal type.
- **Footer**: light grey bar with small text.

## Imagery & icons

- Only Wikimedia images that belong to a case, always with author and license visible underneath (never overlaid or cropped away).
- Icons: hand-written inline SVG in the Lucide style (24px grid, 1.75px stroke, round caps), always with a text label.
- No illustrations, no decorative icon grids, no stock photos.

## Voice

- Plain English, short sentences, for a general reader. Facts and evidence, not accusations.
- Name: always "TimeProof"; features: "TimeProof Lens", "Time machine", "Detection quality".
- Readers always with "≈" (upper bound). Never name a Wikipedia account.
- Never say "fake news", "propaganda proven", "caught red-handed", or present a test-campaign case as real.

## Do / Don't

Do:
1. Use ultramarine for brand and structure only; red only where there is evidence.
2. Serif for anything you read, Inter for anything you click or scan.
3. Use `--brand` only as a fill under white text; for blue text or marks on the page background use `--brand-text`.
4. Show the image credit every time an image appears.
5. Keep the "Sample data" badge on any local mock page (screenshots must never pass mock content as real).

Don't:
1. Don't use blue for flags or evidence.
2. Don't use grey text lighter than `--text-2`.
3. Don't reuse the reference's section names, "W" tile, photos or icon grid.
4. Don't let anything look like Wikipedia's own interface or branding.
5. Don't use colour alone to carry meaning (always a label too).
