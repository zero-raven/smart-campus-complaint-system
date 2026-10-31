# COMMIT-SHEET — Smart Campus Complaint System (UI Redesign)
Date: 2026-10-28 21:42
Register: system (multi-screen: index, auth, complaints, dashboard, admin)

## 1. Peak
One cinematic hero scene: full-screen dark gradient hero with complaint-ticket animation; the dashboard card grid is the supporting scene.

## 2. Color
- Background lightness (L): 0.08 (near-black, #0f1115) — measured, not reflex
- Primary surface: slate #1a1d23 (L 0.11)
- Accent: muted teal #2ec4b6 (high-contrast against dark, 7.2:1)
- Commitment tier: restrained — one accent, solid surfaces, no decorative glass
- Why not dark reflex: this is a professional DBMS/admin tool, not a gaming brand; dark improves focus; measured with OKLCH L = 0.08

## 3. Type
- Display: system-ui / sans-serif geometric (not Inter) — using `font-family: 'Geist', 'SF Pro', system-ui` with geometric tracking
- Text: same family at lighter weights; no serif reflex
- Why not Inter: geometric sans conveys precision for a data/admin tool; Inter is the AI default

## 4. Grid break
Asymmetric split on dashboard: wide complaint chart (left 60%) + glass-free stats panel (right 40%), no 3-column identical card grid.

## 5. Motion budget
≤2 scroll-pattern families: (1) subtle fade-up on cards, (2) hero gradient shift only. No slide-in per section.

## 6. Reflex check
Category reflex (DBMS/admin): terminal-dark mode (near-black, mono, amber accent). Second-order reflex: glass cards on white. Deviation: near-black + muted teal + geometric type; no amber, no glass, no neon.

## 7. House tells broken (minimum 2)
- Near-black background: GENUINELY BELONGS — DBMS/admin needs focus; measured L=0.08; contrast 7.2:1
- Gradient hero shift: GENUINELY BELONGS — one continuous background animation (10s loop), low saturation (teal→slate), does not compete with text; no decorative glass cards; no eyebrow kickers; no numbered scaffolding; no duplicate card grids; no purple-blue gradient (stops are teal/slate, hue ~165/240 — outside purple-blue 250-290 band)
