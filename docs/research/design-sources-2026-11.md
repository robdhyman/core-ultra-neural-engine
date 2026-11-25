# Machine-readable design sources (research, 2026-11)

Question: which public, machine-readable UX/UI design sources are closest in quality and format to Refero's style pages, and could serve as the design spec for a deterministic reference renderer of a small document workspace app (list, editor, toolbar, notification)?

Sources opened: 9 (distinct URLs). Two Material repository URLs returned HTTP 404 and were not read.

## Refero

- Home page (https://refero.design/) lists Screens, Flows, UX Patterns, UI Elements, and Sites libraries, plus a Pricing link, a Refero MCP, a Figma plugin, and Terms and Privacy links.
- The Styles page (https://refero.design/styles) is a grid of about 50 named style tiles (for example "Fintech", "Brutalist", "Premium dark"), each shown with an "Aa" preview. The rendered text shows no colour token table, typography scale, spacing values, or component rules.
- No DESIGN.md, token, or prompt export was visible in the page text of either page. A single style's detail page was not opened, so its contents are unverified.
- Paid tier: a "Refero Pro" plan exists, with a Black Friday 40% off banner (https://refero.design/). Whether a free tier gives access to style data is unconfirmed.
- Licence and reuse terms: the Terms link is present but was not opened. Reuse rights are unconfirmed.
- Refero's own material is a visual reference for humans and an MCP for agents, not a versioned, machine-readable token file.

## Candidates

| Candidate | URL | Format | Covers | Licence | Last update | GitHub stars |
|---|---|---|---|---|---|---|
| Google Labs DESIGN.md spec (alpha) | https://raw.githubusercontent.com/google-labs-code/design.md/main/docs/spec.md (repo: https://github.com/google-labs-code/design.md) | Markdown with YAML tokens in front matter or fenced yaml blocks | Colours (with light/dark sub-maps), typography, spacing, rounded, motion, component tokens with `{path}` references. No states group; variants are separate keys. | Apache-2.0 (repo page) | Not shown on page | 29.1k |
| W3C Design Tokens CG format (draft) | https://www.designtokens.org/tr/drafts/format/ | JSON (`.tokens`, `.tokens.json`) | Single values: colour, dimension, fontFamily, fontWeight, duration, cubicBezier, number. Composites: strokeStyle, border, transition, shadow, gradient, typography. | Not confirmed in the fetched portion | Draft dated 08 September 2026 | Not applicable |
| Primer primitives | https://github.com/primer/primitives | JSON5 source using `$value`, `$type`, `$extensions`, compiled with Style Dictionary | Colour, typography, spacing, size, border, breakpoints, motion. Radius and elevation not mentioned. | MIT | Not shown on page | 422 |
| Open Props | https://github.com/argyleink/open-props | CSS custom properties, plus JSON exports (Design Tokens, Figma, Style Dictionary) | Colours, gradients, shadows, typography, easings, animations, sizes, borders, z-index. Radius and spacing not explicitly listed. | Not stated on page (LICENSE file linked, not opened) | Not shown on page | 5.6k |
| Adobe Spectrum design data | https://github.com/adobe/spectrum-design-data | Not stated (`packages/tokens` directory) | Not itemised on page; described as tokens, component schemas, and guidelines | Apache-2.0 | Not shown on page | 158 |

## Gaps

- Refero style detail pages were not opened, so no token-level content is verified.
- Refero Terms and Privacy pages were not opened; reuse and licence terms for Refero content are unconfirmed.
- Refero free-tier access to style data is unconfirmed; pricing details were not read.
- No repository in the table shows a last-commit date on the fetched page, so recency is unverified for all rows.
- Open Props licence not confirmed (LICENSE file not opened).
- W3C DTCG draft licence not confirmed (the fetched portion did not state it).
- Google DESIGN.md example files were not read; only the README's inline example was seen.
- Material 3 token repositories (material-foundation) returned 404 at the URLs tried; not verified.
- shadcn/ui registry (https://ui.shadcn.com/docs/registry) opened, but its field list and licence were not confirmed.
- No curated collection of DESIGN.md files on GitHub was found or verified.
- DESIGN.md spec is alpha; field names may change.

## Top pick

Google Labs DESIGN.md (https://github.com/google-labs-code/design.md): it combines machine-readable YAML tokens with prose rationale, covers colour, typography, spacing, rounded, motion, and component tokens, exports to W3C DTCG JSON, and is explicitly Apache-2.0. Caveat: alpha status.

## Follow-up

### Refero style detail pages

- Page "Checkout flow with PayPal option" (https://refero.design/styles/5fdd662c-cec5-4b8e-aa80-444dcbc3b7a0): shows DESIGN.md, Copy .md, and Download .md controls plus Color Palette, Typography, Type scale, Fonts, and Guidelines tabs. Hex values were not read on this page; the text view showed no token values. Whether the tabs are gated was not tested.
- Page "teenage engineering" (https://refero.design/styles/8b0c66e4-0163-4880-b27f-3fd0fc39264e): shows concrete hex colours (for example #000000, #ff5000, #f5f7f6), a type scale in px with weights and line heights, font substitutes, and Do / Don't guidelines with px values. It also shows DESIGN.md, Copy .md, and Download .md controls. The page displayed these without a sign-in prompt; the only paid signal seen was a "Refero Pro" banner. Whether the .md export itself requires Pro was not tested.
- Refero's hosted styles library (https://styles.refero.design/, titled "Website Styles & DESIGN.md Library | Refero Styles") was opened; its contents beyond the title were not read in detail.

### VoltAgent/awesome-design-md

- Repository (https://github.com/VoltAgent/awesome-design-md): the README lists 83 DESIGN.md entries by my count (the badge says 84), grouped by category (AI & LLM platforms, developer tools, fintech, media, automotive, and others). MIT licence, about 128.9k stars, 69 commits on main; last-update date not visible.
- Format: described as a "Stitch DESIGN.md format" with sections for theme, colour, typography, components, layout, depth, do's and don'ts, and an agent prompt guide. The fetch did not confirm YAML front-matter tokens, so this is treated as structured Markdown unless the files are checked directly.
- Origin: the README says the files are extracted from public websites and capture publicly visible CSS values. It does not say whether they are hand-written or AI-generated. It states they are provided "as is" and that the maintainers claim no ownership of any site's visual identity; contributors are asked to fix wrong colours, so extractions can contain errors.
- Calm-workspace candidates named in the README (individual files were not opened): Notion ("warm minimalism, serif headings, soft surfaces"), Mintlify ("clean, green-accented documentation style"), and Linear ("ultra-minimal and precise"). Their links point to https://getdesign.md/notion/design-md, https://getdesign.md/mintlify/design-md, and https://getdesign.md/linear.app/design-md, which were not opened directly.
