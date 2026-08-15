---
version: alpha
name: "Tropical Hacker Fest"
description: "Hacker House Goa is a bold, festival-style event landing page built on a deep forest-green (#0b6839) canvas. Massive serif display type (Imbue) in electric yellow dominates the hero, while a monospaced body font (Victor Mono) handles all supporting text. A hot-pink (#ff0080) accent. used for the Devanagari \"गोवा\" badge. provides a single vivid pop of contrast. The CTA button is a flat yellow rectangle with a subtle yellow glow shadow. Illustrated palm trees and a rising sun reinforce the Goa tropical theme. The design is intentionally flat with zero card elevation, relying entirely on color contrast and typographic scale for hierarchy."
colors:
  forest-green: "#0b6839"
  black: "#000000"
  electric-yellow: "#fee101"
  golden-yellow-alt: "#edd723"
  hot-pink: "#ff0080"
  white: "#ffffff"
  cream: "#fffbe8"
typography:
  hero-display:
    fontFamily: "Imbue"
    fontSize: "67px"
    fontWeight: "700"
    lineHeight: "51.7px"
  section-heading:
    fontFamily: "Imbue"
    fontSize: "42px"
    fontWeight: "700"
    lineHeight: "44.1px"
  medium-heading:
    fontFamily: "Imbue"
    fontSize: "34px"
    fontWeight: "500"
    lineHeight: "40.8px"
  label-caps:
    fontFamily: "Imbue"
    fontSize: "15px"
    fontWeight: "800"
    lineHeight: "22.5px"
    letterSpacing: "1.5px"
  body-default:
    fontFamily: "Victor Mono"
    fontSize: "16px"
    fontWeight: "400"
    lineHeight: "24px"
  nav-link:
    fontFamily: "Victor Mono"
    fontSize: "22px"
    fontWeight: "700"
    lineHeight: "26.4px"
  small-label:
    fontFamily: "Victor Mono"
    fontSize: "12.5px"
    fontWeight: "400"
    lineHeight: "18.75px"
  mono-bold-label:
    fontFamily: "Victor Mono"
    fontSize: "14px"
    fontWeight: "700"
    lineHeight: "17.5px"
    letterSpacing: "0.35px"
  imbue-small-bold:
    fontFamily: "Imbue"
    fontSize: "11px"
    fontWeight: "700"
    lineHeight: "16.5px"
    letterSpacing: "0.275px"
rounded:
  radius-sm: "6px"
  radius-md: "10px"
  radius-base: "0.625rem"
  radius-none: "0px"
spacing:
  space-1: "4px"
  space-2: "8px"
  space-3: "10px"
  space-4: "12px"
  space-5: "16px"
  space-6: "20px"
  space-7: "24px"
  space-8: "28px"
  space-9: "30px"
  space-10: "32px"
  space-11: "36px"
  space-12: "40px"
  space-13: "48px"
  space-14: "80px"
---

## Overview

Hacker House Goa is a bold, festival-style event landing page built on a deep forest-green (#0b6839) canvas. Massive serif display type (Imbue) in electric yellow dominates the hero, while a monospaced body font (Victor Mono) handles all supporting text. A hot-pink (#ff0080) accent. used for the Devanagari "गोवा" badge. provides a single vivid pop of contrast. The CTA button is a flat yellow rectangle with a subtle yellow glow shadow. Illustrated palm trees and a rising sun reinforce the Goa tropical theme. The design is intentionally flat with zero card elevation, relying entirely on color contrast and typographic scale for hierarchy.

**Signature traits:**
- Dual typeface system: Pairs Imbue and Victor Mono across the type hierarchy.
- Layered elevation: Depth comes from 1 validated shadow token.

## Colors

The palette uses 7 validated color tokens across 1 theme profile. Semantic roles stay attached to observed usage so generation agents can choose accents without inventing new color meaning.

**Semantic naming:**
- **surface-background** maps to `forest-green`: Role "background" is grounded by usage context "Full-page background, all surface fills, card, popover, sidebar — the dominant canvas color".
- **action-text** maps to `electric-yellow`: Role "text" is grounded by usage context "Hero headline text, CTA button fill, logo text, secondary brand color — the primary action and display color".
- **surface-text** maps to `hot-pink`: Role "text" is grounded by usage context "Devanagari 'गोवा' badge background, accent highlights — single vivid pop color".
- **content-text** maps to `golden-yellow-alt`: Role "text" is grounded by usage context "Illustration line details, sun rays, decorative strokes on the hero illustration".

### Text Scale
- **Black** (#000000): Secondary foreground on yellow surfaces (CTA button label contrast). Role: text. {authored: rgb(0, 0, 0), space: rgb}
- **Electric Yellow** (#fee101): Hero headline text, CTA button fill, logo text, secondary brand color — the primary action and display color. Role: text. {authored: rgb(254, 225, 1), space: rgb}
- **Golden Yellow Alt** (#edd723): Illustration line details, sun rays, decorative strokes on the hero illustration. Role: text. {authored: rgb(237, 215, 35), space: rgb}
- **Hot Pink** (#ff0080): Devanagari 'गोवा' badge background, accent highlights — single vivid pop color. Role: text. {authored: rgb(255, 0, 128), space: rgb}
- **White** (#ffffff): Body text, nav links, subheadings, CTA button text foreground. Role: text. {authored: rgb(255, 255, 255), space: rgb}

### Interactive
- **Cream** (#fffbe8): Subtle border/outline details on the CTA button dashed border pattern. Role: border. {authored: rgb(255, 251, 232), space: rgb}

### Surface & Shadows
- **Forest Green** (#0b6839): Full-page background, all surface fills, card, popover, sidebar — the dominant canvas color. Role: background. {authored: rgb(11, 104, 57), space: rgb, alpha: 0.95}

## Typography

Typography uses Imbue, Victor Mono across extracted hierarchy roles. Keep hierarchy mapped to these token rows before adding decorative type styles.

Mixes Imbue and Victor Mono for visual contrast. Weight range spans bold, medium, regular. Sizes range from 11px to 67px.

### Font Roles
- **Headline Font**: Imbue
- **Body Font**: Imbue

### Type Scale Evidence
| Role | Font | Size | Weight | Line Height | Letter Spacing | Stack / Features | Notes |
|------|------|------|--------|-------------|----------------|------------------|-------|
| Primary hero headline — 'HACKER HOUSE' massive display text | Imbue | 67px | 700 | 51.7px | normal | Imbue, Imbue Fallback | Extracted token |
| Section-level headings and large subheadings | Imbue | 42px | 700 | 44.1px | normal | Imbue, Imbue Fallback | Extracted token |
| Mid-level headings and feature titles | Imbue | 34px | 500 | 40.8px | normal | Imbue, Imbue Fallback | Extracted token |
| Uppercase label text, category tags, small caps labels | Imbue | 15px | 800 | 22.5px | 1.5px | Imbue, Imbue Fallback | Extracted token |
| Primary body copy, paragraph text, general content | Victor Mono | 16px | 400 | 24px | normal | Victor Mono, Victor Mono Fallback | Extracted token |
| Navigation links and prominent inline links | Victor Mono | 22px | 700 | 26.4px | normal | Victor Mono, Victor Mono Fallback | Extracted token |
| Small supporting text, captions, metadata | Victor Mono | 12.5px | 400 | 18.75px | normal | Victor Mono, Victor Mono Fallback | Extracted token |
| Bold mono labels, button text, tag text | Victor Mono | 14px | 700 | 17.5px | 0.35px | Victor Mono, Victor Mono Fallback | Extracted token |
| Micro labels, badge text, fine-print headings | Imbue | 11px | 700 | 16.5px | 0.275px | Imbue, Imbue Fallback | Extracted token |

## Layout

Responsive system uses 1 breakpoint tier(s): desktop.

This system uses a 4px base grid with scale values 4, 8, 10, 12, 16, 20, 24, 28, 30, 32, 36, 40, 48, 80.

### Responsive Strategy
- **desktop (Unknown)**: Expand layout density and horizontal composition for wide viewports.

### Spacing System
| Token | Value | Px | Notes |
|------|-------|----|-------|
| space-1 | 4px | 4 | Extracted spacing token |
| space-2 | 8px | 8 | Extracted spacing token |
| space-3 | 10px | 10 | Extracted spacing token |
| space-4 | 12px | 12 | Extracted spacing token |
| space-5 | 16px | 16 | Extracted spacing token |
| space-6 | 20px | 20 | Extracted spacing token |
| space-7 | 24px | 24 | Extracted spacing token |
| space-8 | 28px | 28 | Extracted spacing token |
| space-9 | 30px | 30 | Extracted spacing token |
| space-10 | 32px | 32 | Extracted spacing token |
| space-11 | 36px | 36 | Extracted spacing token |
| space-12 | 40px | 40 | Extracted spacing token |
| space-13 | 48px | 48 | Extracted spacing token |
| space-14 | 80px | 80 | Extracted spacing token |

## Elevation & Depth

Keep depth flat unless validated shadow or interaction evidence appears in the extraction payload. Do not invent shadows beyond this evidence boundary.

### Shadow Evidence
| Shadow Token | Layers | Details |
|--------------|--------|---------|
| card-drop | 1 | 0px 4px 12px 0px rgba(0, 0, 0, 0.3) |

### Interaction Signals
| Theme | Signal | Evidence |
|-------|--------|----------|
| Light | backdrop-filter | blur(4px) |
| Light | outline-color | oklch(0.905801 0.188095 99.8014 / 0.5) |
| Light | outline-width | 3px |
| Light | outline-offset | 0px |
| Light | transform | matrix(1, 0, 0, 1, 0, 2750) ; matrix(1, 0, 0, 1, 0, 28) ; matrix(1, 0, 0, 1, 0, -3999) |

## Shapes

Shape language maps directly to rounded tokens. Keep component corners consistent with the role mapping below before introducing bespoke geometry.

### Radius Roles
| Token | Value | Px | Role Mapping |
|------|-------|----|--------------|
| radius-none | 0px | 0 | Hairline corner |
| radius-sm | 6px | 6 | Subtle corner |
| radius-md | 10px | 10 | Control corner |
| radius-base | 0.625rem | 10 | Control corner |

### Geometry Evidence
| Radius Token | Shape | Units |
|--------------|-------|-------|
| radius-sm | 6px | px |
| radius-md | 10px | px |
| radius-base | 0.625rem | rem |
| radius-none | 0px | px |

## Components

(none detected)

## Do's and Don'ts

Guardrails protect Dual typeface system, Layered elevation without adding unsupported visual claims.

| Do | Don't |
|----|---------|
| Do maintain consistent spacing using the base grid | Don't make unsupported claims about absent visual features |
| Do maintain WCAG AA contrast ratios (4.5:1 for normal text) | Don't mix rounded and sharp corners in the same view |
| Do use the primary color only for the single most important action per screen |  |
| Do verify evidence before writing new design-system guidance |  |

## Responsive Evidence

### Breakpoints
| Name | Width | Key Changes |
|------|-------|-------------|
| Breakpoint 1 | Unknown | (prefers-reduced-motion: reduce) |

## Agent Prompt Guide

### Example Component Prompts
- Create button component using validated primary color role and spacing tokens.
- Create card component with mapped radius role and evidence-backed elevation.
- Create form input component using inferred typography hierarchy and border roles.

### Iteration Guide
1. Start with extracted palette and typography roles only.
2. Map spacing and radius directly from token tables before visual polish.
3. Apply component patterns one section at a time and compare against source intent.
4. Keep elevation claims tied to explicit evidence in output.
5. Iterate with smallest diffs and re-check section hierarchy after each change.
