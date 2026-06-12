# UI refactor incremental

Este refactor separa componentes Streamlit sin cambiar comportamiento ni lógica de negocio.

## Movido desde `ui/app.py`

- Navegación principal, navegación Lab y estilos de shell:
  - Nuevo archivo: `ui/app_shell.py`
  - Funciones principales: `render_app_shell()`, `render_lab_navigation()`, `inject_shell_styles()`
  - Constantes reexportadas por compatibilidad: `NAV_ITEMS`, `DEMO_NAV_ITEMS`

`ui/app.py` queda como entrypoint, router de páginas y sidebar técnico.

## Movido desde `ui/pages/tasacion.py`

- Formulario de tasación:
  - Nuevo archivo: `ui/valuation/form.py`
  - Funciones principales: `render_valuation_form()`, `build_valuation_payload()`

- Resultado de tasación, confianza y comparables:
  - Nuevo archivo: `ui/valuation/result.py`
  - Funciones principales: `render_valuation_result()`, `render_comparables_compact()`,
    `valuation_quality_state()`

- Hero, banner demo, accesos rápidos y panel contextual:
  - Nuevo archivo: `ui/valuation/landing.py`
  - Funciones principales: `render_home_hero()`, `render_demo_notice()`,
    `render_quick_access()`, `render_context_panel()`

`ui/pages/tasacion.py` queda como orquestador de página. Mantiene aliases privados
para no romper imports/tests existentes durante la transición.
