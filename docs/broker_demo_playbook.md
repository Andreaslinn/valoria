# Broker Demo Playbook

Objetivo: que un broker entienda el valor de AVM en menos de 5 minutos.

Esta demo no agrega funcionalidades nuevas. Usa el Demo Mode y dataset demo ya
incluidos en AVM-v2 para contar una historia clara: buscar, tasar, revisar
comparables y terminar con radar de oportunidades.

## Preparacion Antes De La Demo

1. Levantar API y UI.
2. Entrar a Streamlit.
3. Activar `Modo demo` en la barra lateral.
4. Elegir escenario `comprador` o `inversionista`.
5. Presionar `Cargar datos demo`.
6. Mantener la navegacion simple:
   - `Dashboard Lab`
   - `Tasar propiedad`
   - `Radar`
   - `Property Experience` solo si el broker pide detalle.

No abrir configuraciones tecnicas durante la demo.

## Flujo Ideal En 5 Minutos

### 0:00 - 0:45 | Contexto

Mensaje:

> "La idea no es reemplazar tu criterio. Es darte una primera lectura rapida:
> valor estimado, confianza, comparables y oportunidades para priorizar donde
> mirar."

Pantalla: `Dashboard Lab`.

Mostrar:

- oportunidad prioritaria
- alertas recientes
- portafolio demo
- movimiento de precio

Valor para broker:

- menos tiempo revisando publicaciones una por una
- priorizacion de conversaciones
- argumentos para cliente comprador o vendedor

### 0:45 - 2:10 | Tasacion

Pantalla: `Tasar propiedad`.

Usar ejemplo:

| Campo | Valor |
|---|---|
| Tipo | Departamento |
| Comuna | nunoa |
| m2 | 65 |
| Dormitorios | 2 |
| Banos | 2 |
| Estacionamientos | 1 |
| Precio publicado UF | 4550 |

Presionar `Cargar ejemplo demo` si esta disponible.

Mostrar:

- valor estimado UF/CLP
- confidence score
- comparables usados
- LOW_DATA_MODE si aplica
- warnings de geocoding/tipo/datos

Mensaje:

> "Lo importante aca no es solo el numero. Es si el numero es defendible. Por
> eso mostramos comparables, cantidad de datos y advertencias."

### 2:10 - 3:10 | Comparables

Pantalla: seguir en resultado de tasacion.

Mostrar:

- lista compacta de comparables
- comuna/m2/precio
- similitud

Mensaje:

> "Esto convierte la conversacion con el cliente en algo verificable: estos son
> los comparables que sostienen la estimacion."

Momento de valor:

- el broker puede explicar rapidamente por que una propiedad esta cara, barata
  o en linea con mercado.

### 3:10 - 4:30 | Radar

Pantalla: `Radar`.

Accion:

- dejar `Resultados = 20`
- presionar `Actualizar radar`

Mostrar:

- oportunidades destacadas
- descuento vs estimado
- confianza
- score
- URL/demo listing

Mensaje:

> "Radar invierte el flujo: en vez de tasar una propiedad que ya tengo, me dice
> cuales deberia mirar primero."

### 4:30 - 5:00 | Cierre

Mensaje:

> "Para un broker, esto sirve como copiloto: prioriza propiedades, arma una
> opinion defendible y ayuda a explicar riesgos sin esconder la incertidumbre."

Cerrar con pregunta:

> "En tu flujo real, donde te duele mas: captar propiedades, defender precio con
> el vendedor, o encontrar oportunidades para compradores?"

## Ejemplos Demo Estables

Usar estos ejemplos como anclas. Estan validados por tests para evitar que la
demo se rompa sin aviso.

| ID | Uso | Titulo | Comuna | Mensaje |
|---:|---|---|---|---|
| 9101 | Wow inicial | Departamento luminoso cercano a Plaza Nunoa | nunoa | Bajo mercado + rebajas + negociacion. |
| 9102 | Broker tradicional | Depto remodelado en Providencia con metro cercano | providencia | Alta liquidez y margen moderado. |
| 9104 | Inversionista | Unidad compacta con buena conectividad en Macul | macul | Ticket bajo + arriendo + bajo mercado. |
| 9109 | Riesgo | Departamento con alerta legal simulada en Santiago | santiago | Descuento atractivo, pero requiere due diligence. |
| 9110 | Comparable sano | Departamento 2D2B sector Irarrazaval | nunoa | Sirve para explicar comparables. |

## Momentos De Wow

- `Dashboard Lab`: "Que cambio hoy" muestra que el producto no es una tabla,
  sino una bandeja de decisiones.
- `Tasar propiedad`: el bloque de confianza hace dificil vender humo; eso da
  credibilidad.
- `Comparables`: el broker ve argumentos concretos para defender precio.
- `Radar`: cambia de herramienta reactiva a herramienta proactiva.
- `Price history demo`: rebajas consecutivas ayudan a contar una historia de
  negociacion.
- `Risk/legal demo`: muestra que AVM puede crecer hacia due diligence, sin
  prometer que ya esta conectado a CBR real.

## Fricciones A Evitar

- No empezar por login o configuraciones.
- No mostrar paginas Lab que no entren en la historia.
- No hablar de arquitectura, scrapers o modelos salvo que pregunten.
- No prometer exactitud notarial ni tasacion bancaria.
- No esconder LOW_DATA_MODE ni warnings. Usarlos como prueba de seriedad.

## Frase De Posicionamiento

> "AVM ayuda a un broker a pasar de intuicion a argumento: estima, muestra
> comparables, advierte cuando hay poca data y prioriza oportunidades."

## Checklist De Calidad Antes De Mostrar

- Demo Mode activo.
- Dataset demo cargado.
- `Dashboard Lab` abre sin errores.
- Tasacion demo devuelve comparables.
- Warnings/confianza visibles.
- Radar devuelve oportunidades.
- No hay datos reales sensibles en pantalla.
- Si la API real falla, usar el flujo demo sin detener la presentacion.
