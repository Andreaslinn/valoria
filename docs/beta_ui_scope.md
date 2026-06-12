# Beta UI Scope

Milestone 10 keeps the private beta focused on factual AVM surfaces and hides
demo-heavy UI without deleting code.

## Visible by default in BETA_MODE

- Tasar propiedad: manual valuation, URL analysis, comparables and downloadable simple Risk Report HTML.
- Radar: beta-safe opportunity scanner with scope/verdict flags.
- Estado: lightweight debug/health view.

## Hidden by default in BETA_MODE

- Product Lab pages: Dashboard Lab, Alertas Lab, Checklist Lab, Decision Board Lab, Buyer Journey, Owner Journey, Property Experience, Autofact Demo, Portfolio Demo.
- Demo Risk Report page: the factual report path is the downloadable HTML from Tasacion/Radar.
- Portafolio: watchlist/portfolio remains useful, but is outside the first factual beta scope.
- Alertas: alerts are not mature enough to be core beta.

These pages are hidden because many use simulated or hardcoded data and can
distract from the engine quality signals that matter for beta validation.

## Flags

Configure in `.env` or hosting environment:

```env
BETA_MODE=true
BETA_SHOW_PRODUCT_LAB=false
BETA_SHOW_PORTFOLIO=false
BETA_SHOW_ALERTS=false
BETA_SHOW_STATUS=true
```

Set an override to `true` only for internal demos or debugging sessions.
