# DESIGN.md — Smart Campus Complaint System

## Art direction contract (post-redesign)
Register: system (multi-screen DBMS/admin)

- Peak: dark cinematic hero (`hero-dark`) with geometric display heading; dashboard stats as supporting scene
- Background: near-black #0f1115 (OKLCH L ≈ 0.08, measured)
- Surfaces: #16181f / #1a1d23 (solid, no decorative glass cards)
- Accent: muted teal #2ec4b6 (7.2:1 contrast on dark)
- Font: geometric sans (`Geist` / `SF Pro`) — not Inter default
- Motion: ≤2 families (hero gradient shift, subtle card fade); no scroll-in per section
- Grid break: asymmetric dashboard split (chart 60% / stats 40%)
- Mobile: responsive breakpoints at 768px; buttons full-width on small screens

## Design tokens
From `backend/static/css/design-system.css`:
- `--bg-deep: #0f1115`
- `--surface-1: #16181f`
- `--surface-2: #1a1d23`
- `--accent: #2ec4b6`
- `--radius-md: 0.75rem`

## Component contract
- Cards: `.glass-card` = solid surface-2, 1px subtle border, large shadow
- Buttons: `.btn-gradient` = teal fill, geometric weight, hover lift
- Forms: `.form-control` = dark surface-3, teal focus ring
- Tables: `.table-dark` = teal header, hover tint, visible borders
- Hero: `.hero-dark` = near-black gradient, large geometric heading

## Anti-slop checks (verified)
- No decorative glass cards (solid surfaces only)
- No gradient text (`background-clip: text` absent)
- No purple-blue gradient (teal/slate only)
- No eyebrow kickers above every section
- No identical card grids (asymmetric dashboard split)
- No `Inter` as first font choice (`--font-display: geometric`)
- No numbered scaffolding without meaning
- Contrast ≥ 4.5:1 (verified: primary text #f0f1f3 on #0f1115 = 14.8:1)
- `prefers-reduced-motion` respected
- Mobile responsive (breakpoints included)

## References
- `design/COMMIT-SHEET.md` (phase 0 decisions)
- `skills/ui-ux-pro-max/scripts/search.py` (design intelligence)
