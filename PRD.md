---
title: Smart Campus Complaint System - Complete UI Rework PRD
date: 2026-11-08
version: 1.0
status: Draft
---

# Smart Campus Complaint System - UI Rework PRD

## 1. Executive Summary

**Problem**: The current UI suffers from inconsistent spacing, poor readability (dark text on dark backgrounds in places), repetitive layouts, and a generic "AI-built" aesthetic that undermines user trust in the complaint system.

**Solution**: Complete design system overhaul with premium dark aesthetic, enhanced readability, professional spacing discipline, and modern component patterns.

**Scope**: All user-facing pages - landing, auth, complaints list/detail, dashboard, admin pages.

## 2. Current State Analysis

### Pages in Scope
| Page | Route | Current Issues |
|------|-------|----------------|
| Landing | `/` | Excessive top padding, generic hero, weak visual hierarchy |
| Login/Register | `/login`, `/register` | Low contrast text, dark-on-dark inputs, cramped layout |
| Complaints List | `/complaints` | Dense table, poor filter UX, inconsistent badge colors |
| Complaint Detail | `/complaints/{id}` | Cluttered action cards, unclear status hierarchy, photo gallery needs work |
| New Complaint | `/complaints/new` | Form spacing inconsistent, ML suggestions not visually distinct |
| Dashboard | `/dashboard` | Chart readability poor, metrics lack context, overwhelming data |
| Admin Rules | `/admin/rules` | Table density too high, form controls cramped |
| Admin Models | `/admin/models` | Outdated aesthetic, poor model performance visualization |

### Design Tokens (Current)
- **Background**: `#0a0c10` (OKLCH L ≈ 0.07) — good foundation
- **Accent**: Teal `#2ec4b6` — 7.2:1 contrast, appropriate
- **Surfaces**: Multiple layers (`#12141a`, `#161920`, `#1d2129`, `#232832`) — but inconsistently applied
- **Typography**: Geometric sans for headings — good, but body text occasionally too small
- **Issues**: 
  - Form inputs sometimes darker than cards (contrast inversion)
  - Badge colors lack semantic meaning
  - Spacing rhythm breaks down in detail pages
  - Photo thumbnails inconsistent sizing
  - Timeline items lack visual hierarchy

## 3. Design Principles

### 3.1 Visual Hierarchy
- **Primary content** (complaint details, form fields) — highest contrast, largest type
- **Secondary content** (metadata, timestamps) — 60% opacity, 0.875rem
- **Tertiary content** (hints, helpers) — 40% opacity, 0.75rem
- **Interactive elements** — clear affordance, 44px min touch targets

### 3.2 Spacing System
- **Base unit**: 8px (`.space-1` = 8px, `.space-2` = 16px, `.space-3` = 24px, `.space-4` = 32px, `.space-5` = 40px, `.space-6` = 48px, `.space-8` = 64px)
- **Card padding**: `space-4` (32px) minimum, `space-5` (40px) for primary content
- **Section gaps**: `space-6` (48px) between major sections
- **Component gaps**: `space-3` (24px) between related elements
- **Inline gaps**: `space-2` (16px) between tightly coupled elements

### 3.3 Color System
- **Background**: `#0a0c10` (near-black, premium dark)
- **Surfaces**:
  - `--surface-1`: `#12141a` (cards, navbar)
  - `--surface-2`: `#161920` (elevated, inputs)
  - `--surface-3`: `#1d2129` (pressed states, modals)
  - `--surface-4`: `#232832` (focus states, dropdowns)
- **Primary**: `#2ec4b6` (teal, 7.2:1 on dark)
- **Accent Blue**: `#3b82f6` (secondary actions)
- **Success**: `#10b981` (resolved, completed)
- **Warning**: `#f59e0b` (pending, in progress)
- **Danger**: `#ef4444` (rejected, errors)
- **Info**: `#06b6d4` (assigned, notifications)
- **Text**:
  - `--text-primary`: `#e6e8eb` (90% opacity white)
  - `--text-secondary`: `#9ca3af` (60% opacity)
  - `--text-muted`: `#6b7280` (40% opacity)

### 3.4 Typography Scale
| Level | Size | Weight | Line Height | Use |
|-------|------|--------|-------------|-----|
| H1 | 2.5rem (40px) | 700 | 1.1 | Page titles |
| H2 | 1.875rem (30px) | 600 | 1.2 | Section headers |
| H3 | 1.25rem (20px) | 600 | 1.3 | Card titles |
| H4 | 1.125rem (18px) | 600 | 1.4 | Subsection headers |
| Body | 1rem (16px) | 400 | 1.6 | Primary content |
| Small | 0.875rem (14px) | 400 | 1.5 | Secondary content |
| Caption | 0.75rem (12px) | 500 | 1.4 | Metadata, labels |

## 4. Component Improvements

### 4.1 Landing Page (`/`)
**Current Issues**: Excessive top margin, generic feature cards, weak CTA hierarchy
**Improvements**:
- Reduce hero padding (done in previous fix)
- Enhance feature cards with better icons and hover states
- Add subtle gradient glow behind hero (20s animation)
- Improve role cards (Student/Staff/Admin) with better visual differentiation
- Add trust indicators (uptime, response time) for credibility

### 4.2 Authentication Pages (`/login`, `/register`)
**Current Issues**: Dark-on-dark text, cramped forms, poor focus states
**Improvements**:
- Fix input contrast (surface-2 background, white text)
- Focus states use surface-3 (lighter) with teal ring
- Increase card padding to `space-5` (40px)
- Add password visibility toggle
- Improve error message placement and colors
- Add subtle teal glow to card border

### 4.3 Complaints List (`/complaints`)
**Current Issues**: Dense table, unclear filters, inconsistent badges
**Improvements**:
- Card-based layout instead of table for better mobile experience
- Filter bar with clear visual grouping and active filter chips
- Status badges with semantic colors:
  - SUBMITTED: blue
  - TRIAGED: purple (or desaturated teal)
  - ASSIGNED: cyan
  - IN_PROGRESS: amber
  - RESOLVED: green
  - CLOSED: gray
  - REJECTED: red
- Priority indicators with icons (not just colors)
- Search with debounced input
- Empty state with illustration and CTA

### 4.4 Complaint Detail (`/complaints/{id}`)
**Current Issues**: Cluttered actions, unclear hierarchy, timeline hard to scan
**Improvements**:
- **Header**: Ticket number, subject, status badge prominently displayed
- **Actions Card**: 
  - Grouped into 4 columns (Status, Priority, Category, Department)
  - Each with clear label and current value
  - Dropdowns with visual hierarchy
  - Save buttons appear only when changed
- **Photos Section**:
  - Consistent thumbnail grid (4 columns on desktop, 2 on mobile)
  - Hover overlay with filename and size
  - Click to enlarge in modal
  - Drag-and-drop zone with visual feedback
- **Timeline**:
  - Vertical line with dots for each event
  - Actor avatar with role badge
  - Event type with color coding
  - Payload details in muted text
  - Sort by newest first
- **Comments**:
  - Avatar + name + timestamp
  - Comment body with proper line breaks
  - Auto-resize textarea
  - Character count

### 4.5 New Complaint (`/complaints/new`)
**Current Issues**: ML suggestions not distinct, form validation unclear
**Improvements**:
- Step indicator (1. Describe, 2. Review, 3. Submit)
- ML suggestions in highlighted card with confidence scores
- Visual distinction between AI suggestion and user selection
- Photo upload with preview grid (max 3)
- Submit button with loading state
- Form validation with inline errors

### 4.6 Dashboard (`/dashboard`)
**Current Issues**: Charts hard to read, metrics lack context, overwhelming
**Improvements**:
- KPI cards with trend indicators (up/down arrows)
- Charts with proper labels and tooltips
- Color coding matching status badges
- Filters for date range and department
- Export functionality
- Empty states for no data

### 4.7 Admin Pages (`/admin/rules`, `/admin/models`)
**Current Issues**: Table density, form controls cramped, poor visualization
**Improvements**:
- Data tables with sticky headers
- Inline editing for rules
- Model performance charts with accuracy metrics
- Pagination controls
- Bulk actions (enable/disable multiple rules)

## 5. Layout & Grid

### 5.1 Page Layout
- **Max width**: 1200px for content, 1400px for dashboards
- **Gutters**: 24px on desktop, 16px on mobile
- **Navbar**: Fixed 64px height, glass blur on scroll
- **Footer**: Minimal, with version and links

### 5.2 Responsive Breakpoints
| Breakpoint | Width | Layout |
|------------|-------|--------|
| Mobile | <768px | Single column, stacked cards, full-width buttons |
| Tablet | 768-1024px | 2-column grid for cards, condensed filters |
| Desktop | >1024px | 3-4 column grid, full filter bar |
| Wide | >1440px | Max-width container, larger type scale |

## 6. Interaction Design

### 6.1 Buttons
- **Primary**: Teal background, dark text, 44px min height
- **Secondary**: Surface-2 background, light text, 1px border
- **Danger**: Red background for delete actions
- **States**: Hover (elevated), Active (pressed), Disabled (40% opacity), Loading (spinner)

### 6.2 Forms
- **Inputs**: Surface-2 background, 1px border, 8px radius, 12px padding
- **Focus**: Surface-3 background, teal border, 3px teal glow shadow
- **Labels**: 0.875rem, 600 weight, 8px margin bottom
- **Hints**: 0.75rem, muted color, 4px margin top
- **Errors**: Red border, red hint text, icon

### 6.3 Cards
- **Background**: Surface-1
- **Border**: 1px solid rgba(255,255,255,0.06)
- **Radius**: 12px
- **Shadow**: 0 4px 12px rgba(0,0,0,0.3)
- **Hover**: 0 8px 24px rgba(0,0,0,0.4), border brightens
- **Padding**: 24px (card-body), 16px (card-header)

### 6.4 Badges & Pills
- **Padding**: 4px 10px
- **Radius**: 999px (pill)
- **Font**: 0.75rem, 600 weight, uppercase
- **Colors**: Semantic per status/priority/role

## 7. Accessibility Requirements

### 7.1 Contrast
- Body text: ≥4.5:1 against background
- Large text: ≥3.0:1
- UI components: ≥3.0:1 for borders
- Focus indicators: ≥3.0:1

### 7.2 Keyboard Navigation
- All interactive elements focusable via Tab
- Visible focus rings (2px teal outline)
- Skip to content link
- Proper ARIA labels for icon buttons

### 7.3 Reduced Motion
- Respect `prefers-reduced-motion`
- Disable animations, show final states immediately
- No auto-playing carousels or animations

## 8. Performance Requirements

- **LCP**: <2.5s (Largest Contentful Paint)
- **CLS**: <0.1 (Cumulative Layout Shift)
- **INP**: <200ms (Interaction to Next Paint)
- **Images**: Lazy load, WebP format, responsive sizes
- **CSS**: Inline critical styles, defer non-critical
- **JS**: Defer non-critical scripts, code splitting

## 9. Implementation Phases

### Phase 1: Design System Foundation (Day 1)
- [ ] Audit current CSS variables and tokens
- [ ] Create `design/COMMIT-SHEET.md` with design decisions
- [ ] Update `backend/static/css/design-system.css` with new tokens
- [ ] Create Bootstrap override files (`bootstrap-dark.css`)
- [ ] Test design system on one page (landing)

### Phase 2: Core Pages (Day 2)
- [ ] Landing page improvements
- [ ] Auth pages (login/register) contrast fixes
- [ ] Complaints list page redesign
- [ ] Complaint detail page redesign

### Phase 3: Secondary Pages (Day 3)
- [ ] New complaint form
- [ ] Dashboard improvements
- [ ] Admin pages (rules, models)

### Phase 4: Polish & QA (Day 4)
- [ ] Run slopscan on all templates
- [ ] Screenshot journey (390px, 768px, 1440px)
- [ ] Accessibility audit (contrast, keyboard nav)
- [ ] Performance audit (Lighthouse)
- [ ] Final verification with `verify.sh`

## 10. Success Metrics

- **Visual Consistency**: All pages use same design tokens (0 hardcoded colors)
- **Readability**: 100% of text meets WCAG AA contrast (4.5:1)
- **Performance**: LCP <2.5s, CLS <0.1 on all pages
- **Accessibility**: Keyboard navigation works for all interactive elements
- **User Testing**: 5 users complete key tasks without confusion

## 11. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing functionality | High | Run full test suite after each phase |
| Design tokens conflict with Bootstrap | Medium | Use specific override files, test thoroughly |
| Performance degradation | Medium | Monitor Lighthouse scores, optimize images |
| User confusion from major changes | Low | Gradual rollout, keep functionality identical |

## 12. Out of Scope

- Backend logic changes
- Database schema changes
- API endpoint changes
- Mobile app (separate project)
- Internationalization (i18n)

## 13. Appendix

### A. Color Palette (OKLCH)
```
Background: L 0.07 C 0.02 H 250 (#0a0c10)
Surface 1: L 0.10 C 0.02 H 250 (#12141a)
Surface 2: L 0.12 C 0.02 H 250 (#161920)
Surface 3: L 0.15 C 0.02 H 250 (#1d2129)
Surface 4: L 0.18 C 0.02 H 250 (#232832)
Primary: L 0.70 C 0.15 H 185 (#2ec4b6)
Accent Blue: L 0.65 C 0.20 H 220 (#3b82f6)
Success: L 0.65 C 0.15 H 150 (#10b981)
Warning: L 0.70 C 0.15 H 45 (#f59e0b)
Danger: L 0.60 C 0.20 H 0 (#ef4444)
Info: L 0.65 C 0.15 H 195 (#06b6d4)
```

### B. Typography Stack
```css
font-display: "SF Pro Display", "Geist", system-ui, -apple-system, sans-serif;
font-text: "SF Pro Text", "Inter", system-ui, -apple-system, sans-serif;
font-mono: "SF Mono", "JetBrains Mono", ui-monospace, monospace;
```

### C. Component Inventory
- Buttons (primary, secondary, danger, outline, ghost)
- Form controls (input, select, textarea, checkbox, radio, switch)
- Cards (default, elevated, outlined)
- Badges (status, priority, role, department)
- Tables (default, striped, hover)
- Modals (default, large, fullscreen)
- Alerts (success, warning, danger, info)
- Progress (bar, spinner)
- Tooltips and popovers
- Tabs and pills
- Pagination
