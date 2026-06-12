# Product Lab UI Audit

## Scope

Audit of the AVM v2 Product Lab / Demo Mode UI only. Reviewed:

- `ui/app.py`
- `ui/pages/*`
- `ui/components/*`
- `ui/components/theme.py`
- `ui/components/layout.py`
- Dashboard Lab, Radar Lab, Portfolio Demo, Risk Report Demo, Autofact Demo, Buyer Journey, Owner Journey, Alert Center, Checklist Lab, Decision Board Lab, Lab Feedback

No backend/productive mode changes are part of this audit.

## Brutal Diagnosis

The Lab is functionally rich but visually over-explained. It feels like a capable internal prototype rather than a premium fintech product because nearly every insight is presented with the same visual weight: card, metric, expander, caption, repeat. The user can see a lot, but the interface does not decide what matters first.

The main issue is not missing features. The main issue is hierarchy.

## Highest Priority UX Problems

1. Too many expanders

   Expanders are used as both navigation and content framing. This is a classic Streamlit smell. It creates hidden depth, inconsistent disclosure, and accidental nested UI risks. Risk Report, Autofact, Alert Center, Decision Board actions, and property activity all lean on expanders.

2. Too many equal-weight metric cards

   Dashboard, Portfolio, Risk Report, Checklist, Offer Simulator and Owner Journey use rows of 3-5 metric cards repeatedly. Metrics should be a hierarchy, not wallpaper. The current pattern makes important values compete with supporting values.

3. Card overload

   `avm-card` is doing too much: metric tile, content block, alert item, report section, recommendation, feed item, legal flag. Because everything is a card, nothing feels editorially important.

4. Vertical density without progressive focus

   Many pages stack modules linearly: summary, controls, alerts, market, autofact, negotiation, activity, risk, actions. This is powerful but exhausting. Modern fintech dashboards reduce the first viewport to one decision frame and put secondary evidence behind explicit affordances.

5. Navigation is broad but not strategic

   Lab navigation now has many modules: Dashboard, Alertas, Checklist, Decision Board, Buyer Journey, Owner Journey, Risk Report, Autofact, Portfolio, Feedback. It is clear, but not yet product-led. The user still has to understand the system map instead of being guided by a primary workflow.

6. Streamlit widgets remain visually exposed

   Radios, selectboxes, checkboxes, sliders and buttons appear as raw controls in many high-value screens. They make the Lab feel like a toolbench, not a fintech product. This is especially visible in Buyer Journey, Offer Simulator, filters, Checklist and Decision Board.

7. Weak separation between insight and action

   Alerts, reports, checklist, offer simulator and decision board are connected, but visually they still appear as separate modules. The premium experience should say: "Here is the decision, here is the evidence, here is the next action."

8. Repeated demo disclaimers

   The demo labeling is safer now, but too many local disclaimers compete with content. Keep one global Lab disclaimer persistent, then use smaller inline labels where legally important.

9. Tables appear in premium flows

   Dataframes in comparison and Lab Feedback are efficient but visually non-premium. They are acceptable for internal/admin panels, but product-facing demo screens should use ranked lists or compact comparison rows.

10. Visual rhythm is too uniform

   Spacing, card radius and tone are consistent, but the system lacks contrast between overview, detail, evidence, and action. Linear, Revolut and Fintual-style products use stricter rhythm: small toolbar, strong summary, compact insight rows, quiet detail.

## Visually Weakest Modules

1. Risk Report Demo

   It has the right content, but too many sections compete. Scores, legal, market, negotiation, timeline, price history, comparables, comuna context and portal presence all appear as full blocks. It needs a report narrative: summary -> critical blockers -> value thesis -> action plan.

2. Portfolio Demo

   It is useful but dense. Each property card can open too many demo layers. It feels like an aggregator plus debug console rather than a portfolio cockpit.

3. Buyer Journey

   Product concept is strong, but the UI feels like a form-driven wizard. Too many controls and repeated modules are visible at once. It needs a single current step, next action and side evidence.

4. Dashboard Lab

   Good connective tissue, but feeds and metric cards produce a "wall of modules". It needs a stronger first viewport and fewer simultaneous modules.

5. Checklist Lab

   Useful, but item cards plus status dropdown plus note input make it feel operational. It should become a task list with compact rows and focused detail drawer.

## Modules Closest to Premium

1. Decision Board Lab

   Strong product metaphor. It turns analysis into workflow. With tighter cards and fewer inline actions, this can become the Lab's anchor experience.

2. Alert Center Demo

   Strong "live product" signal. Alerts are actionable and connected. Needs better grouping and a priority inbox treatment.

3. Offer Simulator

   Strong buyer value. It has immediate feedback and clear scenario dynamics. Needs better visual framing around "your offer stance" rather than many metrics.

4. Market Context

   Good product intuition. It explains why the property is not isolated. Needs a compact market strip, not a full section everywhere.

## Visual Principles For Next Phase

1. One primary decision per screen

   Every Lab page should answer: what should the user do next?

2. Evidence should be layered

   Summary first, supporting signals second, raw details last.

3. Replace repeated cards with ranked insight rows

   Cards should be reserved for major entities or repeated property items. Supporting facts should become compact rows, chips or inline stat groups.

4. Make the Lab feel like an operating system

   Dashboard, Decision Board and Alerts should form the core loop. Reports and Autofact should be evidence panels, not destinations competing for attention.

5. Reduce exposed Streamlit controls

   Replace raw controls with segmented controls, compact filters, action bars, and inline edit states where possible.

6. Use color less often

   Reserve `negative`, `warning`, `positive`, `premium` for meaningful system states. Too many badges reduce trust.

7. Keep demo safety visible but quiet

   Global disclaimer in shell/sidebar plus specific legal disclaimers only where needed.

## Recommended Product IA

Primary Lab workflow:

1. Dashboard Lab
2. Decision Board Lab
3. Alertas Lab
4. Buyer Journey
5. Portfolio Demo

Evidence modules:

1. Risk Report
2. Autofact Demo
3. Checklist Lab
4. Offer Simulator
5. Market Context

Internal/admin:

1. Lab Feedback

## Roadmap UX

### Phase 1: Cleanup Without Redesign

- Make report components render inline when already inside expanded areas.
- Reduce nested expanders.
- Collapse secondary modules by default.
- Rename technical captions into buyer language.
- Keep Dashboard first viewport to 4-6 decisive signals max.

### Phase 2: Premium Dashboard Treatment

- Create a persistent Lab command header.
- Add a compact "next best action" rail.
- Turn alert/feed cards into dense insight rows.
- Replace large metric grids with one hero metric plus supporting deltas.

### Phase 3: Report Experience

- Redesign Risk Report as:
  - Executive thesis
  - Critical blockers
  - Market/value read
  - Negotiation stance
  - Due diligence checklist
  - Raw evidence
- Merge Autofact signals into the legal section while keeping Autofact as a deep-dive panel.

### Phase 4: Workflow-First Lab

- Make Decision Board the main operating surface.
- Let Alerts, Checklist and Offer Simulator act as contextual panels from each property.
- Reduce standalone pages for modules that are better as side panels.

### Phase 5: Product Validation

- Use Lab Feedback to measure:
  - premium intent
  - confusion
  - repeated use
  - discarded features
- Promote only features that create action, not just information.

## Quick Wins Applied In This Pass

- Added inline rendering support to report-style components so they can avoid nested expanders inside Lab cards/feed contexts.
- Converted Risk Report content sections to inline blocks when embedded.
- Converted Autofact content and legal timeline to inline mode when embedded.
- Added inline mode support for Market Context, Negotiation Signals, Activity, Checklist and Offer Simulator.
- Updated Dashboard feed actions to render embedded Risk Report and Autofact as inline blocks instead of nested expanders.

## Risks And TODOs

- The Lab still has too many feature modules visible as top-level navigation.
- Inline report rendering fixes nested expander errors but does not solve overall density.
- The design system lacks a true compact insight-row component.
- Streamlit still exposes native widgets in premium flows.
- A proper premium redesign should be done around Decision Board + Alerts + Dashboard, not by restyling every module independently.
