# COMMIT-SHEET v2 — Smart Campus Complaint System (Minimalist Corporate)
Date: 2026-10-28 22:24
Register: system (multi-screen DBMS/admin)

## 1. Peak
One signature element: a clean data table with perfect alignment and high-contrast states — the dashboard KPI row is the supporting scene.

## 2. Color
- Background: true off-white #fafafa (OKLCH L ≈ 0.98) — not dark, not cream
- Surface: #ffffff (cards, modals)
- Border: #e5e7eb (subtle, consistent)
- Primary: #1e3a8a (deep blue, 7.8:1 on white)
- Primary hover: #1e40af
- Accent (success): #059669 (emerald, 5.2:1)
- Accent (danger): #dc2626 (red, 5.5:1)
- Accent (warning): #d97706 (amber, 4.6:1)
- Text primary: #111827 (15.3:1)
- Text secondary: #4b5563 (8.6:1)
- Text muted: #9ca3af (3.9:1 — large text only)
- Commitment tier: restrained — one primary blue, semantic colors only

## 3. Type
- Display: "SF Pro Display", "Geist", system-ui, sans-serif (geometric, tight tracking -0.03em)
- Body: same family, lighter weights
- Mono: "SF Mono", "IBM Plex Mono", ui-monospace
- Why not Inter: geometric display conveys precision for admin data

## 4. Grid break
Asymmetric: 280px fixed sidebar (optional) + fluid main; dashboard splits 60/40 with visual weight shift

## 5. Motion budget
0 scroll animations. Only: button 100ms, input focus 120ms, modal 200ms, dropdown 150ms. No hero shift.

## 6. Reflex check
Category reflex (DBMS/admin): terminal dark. Second-order: glassmorphism SaaS. Deviation: light, high-contrast, dense data, zero decoration.

## 7. House tells broken (minimum 2)
- Near-black background: BROKEN — using true white/off-white for data density and print-readability
- Gradient hero shift: BROKEN — zero background animation; hero is a concise H1 + action row
- Decorative glass cards: BROKEN — solid white cards, 1px border, subtle shadow
- Eyebrow kickers: BROKEN — none
- Identical card grids: BROKEN — varied card sizes by content priority
- Purple-blue gradient: BROKEN — single deep blue primary
