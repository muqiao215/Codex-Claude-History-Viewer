# DESIGN.md — Codex & Claude History Viewer

A format for describing this project's visual identity to coding agents. Load
this file whenever you generate or modify UI (HTML/CSS in `static/`) so the
interface stays visually coherent across agent-driven changes.

## Identity

A dense, utilitarian **local developer tool**: a two-pane inbox for agent
transcripts. The visual language is "calm data": light neutral surfaces, one
blue accent, semantic color chips, and zero decoration. It should feel like a
well-organised IDE panel, not a marketing page.

## Design tokens

All colors live as CSS custom properties on `:root` in `static/styles.css`.
Never hardcode hex values in component styles — reference the variables so the
six code themes (`light`, `slate`, `warm`, `forest`, `grape`, `dark`) keep
working.

### Core palette (light theme reference)

| Token | Value | Use |
|---|---|---|
| `--bg` | `#f5f7fb` | App background |
| `--panel` | `#ffffff` | Cards, raised surfaces |
| `--surface-subtle` | `#f8fafc` | Recessed panels (audit, insights) |
| `--surface-hover` | `#eef2ff` | Hover rows/buttons |
| `--surface-selected` | `#dbeafe` | Active session row |
| `--text` | `#1f2937` | Primary text |
| `--muted` | `#6b7280` | Secondary text, labels |
| `--border` | `#dbe3ee` | All 1px borders |
| `--accent` | `#2563eb` | Interactive highlight, bars, links |

### Semantic colors

- Roles: `--assistant` `#e0f2fe`, `--user` `#fef3c7`, `--system` `#f3f4f6`,
  `--thinking` `#ede9fe`.
- Danger: `--danger-bg #fee2e2` / `--danger-border #fca5a5` / `--danger-text #b91c1c`.
- Diff: add `#dafbe1`/`#116329`, del `#ffebe9`/`#cf222e`, hunk `#ddf4ff`/`#0550ae`.
- Search marks: `--mark-bg #fde68a`, active `--mark-active-bg #fbbf24`.

### Typography

- System font stack only (`-apple-system, "Segoe UI", Roboto, …`, including
  `PingFang SC` / `Microsoft YaHei` for CJK). No webfonts.
- Base 13–14px; panel/section labels 10–12px uppercase or `.label` / `.muted`
  classes; tabular numerals (`font-variant-numeric: tabular-nums`) for token
  counts and scores.

### Spacing & shape

- 4px scale: padding 4/8/10/12px, radii 4 (inline code) / 6 (rows) / 8 (panels) / 12px (cards).
- 1px `var(--border)` borders everywhere; shadows only on `--panel` cards used
  for overlay-like content (`.handoff-theme-card`).

## Components

- **Buttons** `.btn` / `.btn.small`: bordered neutral buttons; `.danger` for
  destructive; `.active` (accent border + `--surface-hover`) for toggled panel
  states. Icon prefixes (📊 ⚡ 📰 🗒) are part of the labels.
- **Tabs** `.tab` with `role="tab"` + `aria-selected`; active tab shares the
  `.active` styling.
- **Badges** `.audit-badge` + `badge-*` variants (`badge-files`, `badge-tools`,
  `badge-remote`, `badge-test`, `badge-deploy`, `badge-debug`, `badge-friction`,
  `badge-value`) and `outcome-{signal}` for outcome chips. Badges are compact
  chips with an icon + number; they must remain readable at 11px.
- **Bars** `.audit-bar` / `.usage-bar` with `*-fill` width-percentage spans on
  `--accent` over `--system` track.
- **Panels**: `.audit-panel` and the `.insight-panel` family
  (`#handoffPanel`, `#usagePanel`, `#briefingPanel`, `#planPanel`) live inside
  the session header, are `hidden` by default, toggle via buttons that carry
  `aria-expanded`/`aria-controls`, and scroll internally (`max-height`).
- **Insight rows**: `.usage-row` (label / bar / value grid),
  `.usage-top-row` and `.briefing-item` are clickable (`data-usage-session`),
  `.plan-item` uses native `<details>/<summary>`.
- **Handoff themes**: `.handoff-theme-plain|card|feishu` restyle the rendered
  markdown preview; Feishu theme uses `#3370ff` accents by design (external
  brand, deliberately not `--accent`).

## Iconography

Unicode/emoji glyphs only, one per badge/button, always followed by a space.
Do not introduce an icon font or SVG sprite.

## Accessibility

Every toggle button exposes `aria-expanded` and `aria-controls`; tab lists use
`role="tab"`/`aria-selected`; icon-only buttons need `aria-label` or `title`;
hover states never remove focus visibility.

## Do / Don't

- **Do** add new colors as `:root` tokens and mirror them in every theme block.
- **Do** reuse badge/bar/panel classes before inventing new ones.
- **Don't** add runtime dependencies, build steps, webfonts, or dark-only
  assumptions (all six themes must render panels readably).
- **Don't** hardcode widths that break the resizable sidebar
  (`--sidebar-width`) or the 900px single-column media query.
- **Don't** place primary content below the fold of an insight panel; panels
  scroll, toolbars stay at the top.
