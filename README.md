# Comparador de descuentos de droguerías

Aplicación web (Flask + PostgreSQL en Neon) para cargar y consultar descuentos que ofrecen las droguerías sobre productos de farmacia.

## Estructura

```
app.py                  Rutas web y API (Flask)
base_datos.py           Clase BaseDatos: conexión y consultas a PostgreSQL
crear_base_datos.sql    Esquema de la base (tablas, índices, pg_trgm)
templates/
  base.html             Layout compartido (menú y estilos)
  consultar_ofertas.html  Búsqueda de ofertas (página principal)
  cargar_descuento.html   Carga individual y desde Excel
  productos.html          Alta de productos y de droguería/laboratorio/droga
  login.html              Ingreso con clave
reportes_temporales/    Reportes Excel de productos no encontrados (se crea sola)
app.log                 Log de la aplicación (se crea solo)
.env                    Configuración local (no subir a git)
```

## Instalación

```
pip install flask psycopg2-binary python-dotenv pandas openpyxl
```

En la base, ejecutar una sola vez `crear_base_datos.sql` (incluye `CREATE EXTENSION pg_trgm`, necesaria para la búsqueda por similitud de nombres).

## Configuración (`.env`, junto a `app.py`)

```
DATABASE_URL=postgresql://usuario:password@host/base?sslmode=require
CLAVE_ADMIN=clave-para-cargar-datos
SECRET_KEY=texto-largo-aleatorio
```

## Ejecución

```
python app.py
```

Abrir `http://localhost:5000`. El servidor de Flask es de desarrollo; para uso permanente conviene un servidor WSGI (por ejemplo Waitress) o un contenedor Docker. Los logs salen por consola y también a `app.log`.

## Páginas

| Ruta | Función | Requiere clave |
|---|---|---|
| `/` | Consultar ofertas (filtros, orden, "todos los niveles") | No |
| `/cargar` | Cargar descuento (individual o desde Excel) | Sí |
| `/productos` | Alta de producto y de droguería/laboratorio/droga | Sí |
| `/login`, `/logout` | Ingreso y cierre de sesión | — |

## Modelo de datos

`laboratorios`, `drogas`, `droguerias`, `productos` (con `laboratorio_id`, `droga_id`, `codigo`, `troquel`) y `descuentos`.

Un descuento tiene un **nivel de aplicación**: `producto`, `droga`, `laboratorio` o `general`. `referencia_id` apunta a la tabla que corresponda según el nivel (es `NULL` para `general`).

## Carga desde Excel

Todas las filas se cargan como descuentos a nivel **producto**. La droguería y la fecha de vencimiento (opcional) se eligen en el formulario y valen para todo el archivo; la fecha de carga es siempre la de hoy.

Columnas: `nombre`, `codigo` (código de barras), `troquel`, `porcentaje` (o `descuento`) y `cantidad_minima` (opcional). El orden no importa.

El producto se busca en este orden:
1. `troquel` exacto.
2. `codigo` exacto.
3. `nombre` por similitud de trigramas (`pg_trgm`), con umbral mínimo de 0.5 y verificación de que los números del nombre (dosis, cantidad) estén presentes en el candidato.

Si no hay coincidencia confiable, la fila **no se carga**: queda en un reporte Excel descargable para revisarla y dar de alta el producto manualmente.

## Reglas al guardar un descuento

La "misma oferta" se identifica por `droguería + nivel + a qué aplica`. Si ya hay una vigente:

- Mismo porcentaje, cantidad mínima y vencimiento: no hace nada.
- Algo cambió, mismo día de carga (o solo cambió el vencimiento): se actualiza en el lugar.
- Algo cambió en otro día: se cierra la anterior (`fecha_fin` = día previo) y se crea una nueva.

Nunca hay dos ofertas vigentes para la misma combinación. `cantidad_minima` es un dato secundario: se guarda, pero no define la identidad de la oferta.

## Consulta de ofertas

- Por defecto muestra solo la mejor oferta (mayor porcentaje) de cada producto y droguería, sin importar su nivel. Con "Mostrar todos los niveles" se ven todas las que compiten.
- Orden: mejor oferta primero, o por nombre de producto.
- El filtro de droga es de coincidencia exacta; producto, laboratorio y droguería buscan por texto parcial.
- Las droguerías se guardan siempre en mayúsculas.

## Notas

- La clave protege las páginas y los endpoints que escriben en la base; la consulta es de libre acceso.
- No se permiten fechas de vencimiento anteriores a hoy.
