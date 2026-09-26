"""
app.py
======
Servidor web chico (Flask) para cargar descuentos a mano desde una
pagina HTML, en vez de escribir el INSERT a mano cada vez.

Estructura pensada para crecer: cuando armemos la ventana de consulta
de ofertas (filtrar por droga), se suma como una ruta nueva en este
mismo archivo (o un blueprint aparte si crece mucho) y una plantilla
nueva en templates/ -- no hace falta tocar nada de lo que ya funciona.

Para correrlo:
    pip install flask
    python app.py
Despues abrís http://localhost:5000 en el navegador.
"""

import re
import unicodedata
import uuid
from pathlib import Path
from datetime import date, date as date_type
from decimal import Decimal
import pandas as pd
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from base_datos import BaseDatos

app = Flask(__name__)


def serializar_valor(v):
    """jsonify no sabe convertir Decimal ni date por si solo -- los
    resultados de porcentaje (numeric) y las fechas vienen asi desde
    psycopg2, hay que pasarlos a tipos que sean JSON-nativos."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, date_type):
        return v.isoformat()
    return v


def serializar_fila(fila):
    return {k: serializar_valor(v) for k, v in fila.items()}


@app.route("/")
def index():
    return render_template("cargar_descuento.html")


@app.route("/consultar")
def consultar():
    return render_template("consultar_ofertas.html")


@app.route("/api/buscar")
def api_buscar():
    """Autocompletado generico: /api/buscar?tipo=productos&q=ibupirac
    El frontend llama esto cada vez que el usuario tipea, para elegir
    a que producto/droga/laboratorio/drogueria apunta el descuento."""
    tipo = request.args.get("tipo", "")
    texto = request.args.get("q", "")

    if tipo not in ("productos", "drogas", "laboratorios", "droguerias"):
        return jsonify({"error": "tipo invalido"}), 400

    with BaseDatos() as db:
        resultados = db.buscar_entidad(tipo, texto)

    return jsonify([dict(r) for r in resultados])


@app.route("/api/descuentos", methods=["POST"])
def api_crear_descuento():
    """Recibe el formulario de carga y lo inserta en 'descuentos'."""
    datos = request.get_json(silent=True) or {}

    drogueria_id = datos.get("drogueria_id")
    nivel_aplicacion = datos.get("nivel_aplicacion")
    referencia_id = datos.get("referencia_id") or None
    porcentaje = datos.get("porcentaje")
    fecha_carga = date.today().isoformat()  # siempre hoy; no tiene sentido cargar otra fecha
    fecha_fin = datos.get("fecha_fin") or None
    cantidad_minima = datos.get("cantidad_minima") or None

    # validaciones minimas antes de tocar la base -- coinciden con las
    # restricciones reales de la tabla, para no depender solo del
    # error de Postgres si algo viene mal
    errores = []
    if not drogueria_id:
        errores.append("Falta indicar la droguería.")
    if nivel_aplicacion not in ("producto", "droga", "laboratorio", "general"):
        errores.append("El nivel de aplicación debe ser producto, droga, laboratorio o general.")
    if nivel_aplicacion != "general" and not referencia_id:
        errores.append("Para este nivel de aplicación hay que indicar a qué aplica.")
    if nivel_aplicacion == "general" and referencia_id:
        errores.append("Un descuento 'general' no debe apuntar a nada puntual.")
    if not porcentaje:
        errores.append("Falta el porcentaje.")
    if cantidad_minima is not None:
        try:
            if int(cantidad_minima) <= 0:
                errores.append("La cantidad mínima debe ser mayor a cero.")
        except (TypeError, ValueError):
            errores.append("La cantidad mínima debe ser un número entero.")

    if errores:
        return jsonify({"ok": False, "errores": errores}), 400

    with BaseDatos() as db:
        id_creado, estado = db.insertar_descuento(
            drogueria_id=drogueria_id,
            nivel_aplicacion=nivel_aplicacion,
            referencia_id=referencia_id,
            porcentaje=porcentaje,
            fecha_carga=fecha_carga,
            fecha_fin=fecha_fin,
            cantidad_minima=cantidad_minima,
        )

    return jsonify({"ok": True, "id": id_creado, "estado": estado})


@app.route("/api/ofertas")
def api_ofertas():
    """Busqueda combinada para la pantalla de consulta. Todos los
    parametros son opcionales -- si no vienen, ese filtro se ignora."""
    codigo = request.args.get("codigo") or None
    troquel = request.args.get("troquel") or None
    nombre = request.args.get("nombre") or None
    laboratorio = request.args.get("laboratorio") or None
    droga = request.args.get("droga") or None
    drogueria = request.args.get("drogueria") or None
    porcentaje_minimo = request.args.get("porcentaje_minimo") or None
    # por defecto solo se ven las ofertas ganadoras; el frontend manda
    # "false" explicito cuando el usuario tilda "mostrar todos los niveles"
    solo_mejores = request.args.get("solo_mejores", "true") != "false"
    orden = request.args.get("orden", "porcentaje")
    if orden not in ("porcentaje", "nombre"):
        orden = "porcentaje"

    with BaseDatos() as db:
        resultados = db.buscar_ofertas(
            codigo=codigo,
            troquel=troquel,
            nombre=nombre,
            laboratorio=laboratorio,
            droga=droga,
            drogueria=drogueria,
            porcentaje_minimo=porcentaje_minimo,
            solo_mejores=solo_mejores,
            orden=orden,
        )

    return jsonify([serializar_fila(r) for r in resultados])


@app.route("/productos")
def productos():
    return render_template("productos.html")


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")


def limpiar_codigo(v):
    """Igual criterio que en cargar_productos.py: descarta codigos
    demasiado cortos para ser un codigo de barras real."""
    if v is None or (isinstance(v, float) and v != v):  # None o NaN
        return None
    try:
        s = str(int(float(v))) if float(v).is_integer() else str(v)
    except (ValueError, TypeError):
        s = str(v).strip()
    s = s.strip()
    if not s or len(s) <= 2:
        return None
    return s


@app.route("/api/productos", methods=["POST"])
def api_crear_producto():
    """Alta de un producto individual. Crea el laboratorio y/o la
    droga si no existian todavia (mismo get-or-create del pipeline
    de carga masiva)."""
    datos = request.get_json(silent=True) or {}
    nombre = (datos.get("nombre") or "").strip()
    codigo = limpiar_codigo(datos.get("codigo"))
    troquel = limpiar_codigo(datos.get("troquel"))
    laboratorio = (datos.get("laboratorio") or "").strip() or None
    droga = (datos.get("droga") or "").strip() or None

    if not nombre:
        return jsonify({"ok": False, "errores": ["Falta el nombre del producto."]}), 400

    with BaseDatos() as db:
        laboratorio_id = db.obtener_o_crear_laboratorio(laboratorio)
        droga_id = db.obtener_o_crear_droga(droga)
        id_creado = db.insertar_producto_si_no_existe(
            nombre=nombre, codigo=codigo, troquel=troquel,
            laboratorio_id=laboratorio_id, droga_id=droga_id,
        )

    if id_creado is None:
        return jsonify({
            "ok": False,
            "errores": ["Ya existe un producto con ese código de barras o troquel."],
        }), 400

    return jsonify({"ok": True, "id": id_creado})


def _mapear_columnas_ofertas(columnas):
    """Detecta que columna del excel corresponde a cada campo.
    'codigo de barras' -> productos.codigo. 'codigo' a secas (sin la
    palabra 'barras') o 'troquel' -> productos.troquel, el otro
    identificador unico de la tabla. Son dos columnas DISTINTAS,
    no sinonimos."""
    mapa = {}
    for col in columnas:
        norm = re.sub(r"[^a-z0-9]", "", strip_accents(col).lower())
        if ("nombre" in norm or "producto" in norm) and "nombre" not in mapa:
            mapa["nombre"] = col
        elif "troquel" in norm and "troquel" not in mapa:
            mapa["troquel"] = col
        elif ("barra" in norm or norm == "codigo") and "codigo" not in mapa:
            mapa["codigo"] = col
        elif ("porcentaje" in norm or "descuento" in norm) and "porcentaje" not in mapa:
            mapa["porcentaje"] = col
        elif "cantidad" in norm and "cantidad_minima" not in mapa:
            mapa["cantidad_minima"] = col
    return mapa

        

def _valor_o_none(fila, mapa, clave):
    if clave not in mapa:
        return None
    v = fila.get(mapa[clave])
    return v if pd.notna(v) else None


def _limpiar_texto(v):
    return str(v).strip() if v is not None else None


@app.route("/api/descuentos/excel", methods=["POST"])
def api_cargar_descuentos_excel():
    """Carga masiva de ofertas desde un Excel. Todas las filas son
    descuentos a nivel 'producto', para UNA sola drogueria (se pide
    una vez para todo el archivo, no columna por columna, porque una
    lista siempre viene de un solo proveedor).

    Columnas del excel: nombre, codigo (de barras), troquel,
    porcentaje/descuento, y cantidad_minima (opcional). El producto se
    busca por troquel exacto, despues codigo exacto, y si ninguno
    matchea, por nombre parecido. Lo que no se encuentra NO se
    inventa: se junta en un reporte Excel para cargarlo a mano
    despues en "Productos y catálogos"."""
    archivo = request.files.get("archivo")
    drogueria_texto = (request.form.get("drogueria") or "").strip()
    fecha_fin = (request.form.get("fecha_fin") or "").strip() or None

    if not archivo:
        return jsonify({"ok": False, "errores": ["No se recibió ningún archivo."]}), 400
    if not drogueria_texto:
        return jsonify({"ok": False, "errores": ["Falta indicar la droguería de esta lista."]}), 400

    try:
        df = pd.read_excel(archivo)
    except Exception:
        return jsonify({"ok": False, "errores": ["No se pudo leer el archivo. ¿Es un .xlsx válido?"]}), 400

    mapa = _mapear_columnas_ofertas(df.columns)
    if "nombre" not in mapa:
        return jsonify({
            "ok": False,
            "errores": ["El excel necesita una columna 'nombre' (o 'producto')."],
        }), 400
    if "porcentaje" not in mapa:
        return jsonify({
            "ok": False,
            "errores": ["El excel necesita una columna 'porcentaje' (o 'descuento')."],
        }), 400

    insertados = 0
    sin_cambios = 0
    no_encontrados = []  # filas cuyo producto no existe en la base

    with BaseDatos() as db:
        drogueria_id = db.obtener_o_crear_drogueria(drogueria_texto)

        for i, fila in df.iterrows():
            fila_num = i + 2  # +2: la fila 1 es el encabezado, pandas arranca en 0

            nombre = _limpiar_texto(_valor_o_none(fila, mapa, "nombre"))
            codigo = limpiar_codigo(_valor_o_none(fila, mapa, "codigo"))
            troquel = limpiar_codigo(_valor_o_none(fila, mapa, "troquel"))
            porcentaje = _valor_o_none(fila, mapa, "porcentaje")
            cantidad_minima = _valor_o_none(fila, mapa, "cantidad_minima")

            if not nombre and not codigo and not troquel:
                continue  # fila vacia, no hay nada para buscar
            if porcentaje is None:
                no_encontrados.append({
                    "fila_excel": fila_num, "nombre": nombre, "codigo": codigo,
                    "troquel": troquel, "porcentaje": porcentaje,
                    "cantidad_minima": cantidad_minima, "motivo": "falta el porcentaje",
                })
                continue

            producto_id = db.encontrar_producto(nombre=nombre, codigo=codigo, troquel=troquel)
            if producto_id is None:
                no_encontrados.append({
                    "fila_excel": fila_num, "nombre": nombre, "codigo": codigo,
                    "troquel": troquel, "porcentaje": porcentaje,
                    "cantidad_minima": cantidad_minima, "motivo": "producto no encontrado",
                })
                continue

            try:
                cantidad_minima_final = int(cantidad_minima) if cantidad_minima is not None else None
                porcentaje_final = float(porcentaje)
            except (TypeError, ValueError):
                no_encontrados.append({
                    "fila_excel": fila_num, "nombre": nombre, "codigo": codigo,
                    "troquel": troquel, "porcentaje": porcentaje,
                    "cantidad_minima": cantidad_minima, "motivo": "porcentaje o cantidad con formato inválido",
                })
                continue

            id_guardado, estado = db.insertar_descuento(
                drogueria_id=drogueria_id,
                nivel_aplicacion="producto",
                referencia_id=producto_id,
                porcentaje=porcentaje_final,
                fecha_carga=date.today().isoformat(),
                fecha_fin=fecha_fin,
                cantidad_minima=cantidad_minima_final,
            )
            if id_guardado and estado == "sin_cambios":
                sin_cambios += 1
            elif id_guardado:
                insertados += 1
            else:
                no_encontrados.append({
                    "fila_excel": fila_num, "nombre": nombre, "codigo": codigo,
                    "troquel": troquel, "porcentaje": porcentaje,
                    "cantidad_minima": cantidad_minima, "motivo": "no se pudo guardar",
                })

    reporte_url = None
    if no_encontrados:
        reporte_url = _generar_reporte_no_encontrados(no_encontrados)

    return jsonify({
        "ok": True,
        "total_filas": len(df),
        "insertados": insertados,
        "sin_cambios": sin_cambios,
        "no_encontrados": len(no_encontrados),
        "reporte_url": reporte_url,
    })


REPORTES_DIR = Path(__file__).parent / "reportes_temporales"
REPORTES_DIR.mkdir(exist_ok=True)


def _generar_reporte_no_encontrados(filas):
    """Guarda un excel con los productos que no se pudieron matchear,
    para revisarlos y cargarlos a mano despues. Devuelve la URL desde
    donde descargarlo."""
    nombre_archivo = f"productos_no_encontrados_{uuid.uuid4().hex[:8]}.xlsx"
    df_reporte = pd.DataFrame(filas)
    df_reporte.to_excel(REPORTES_DIR / nombre_archivo, index=False)
    return f"/descargar-reporte/{nombre_archivo}"


@app.route("/descargar-reporte/<nombre_archivo>")
def descargar_reporte(nombre_archivo):
    # secure_filename evita que alguien pida rutas fuera de la carpeta
    # de reportes (ej. "../../algo_sensible")
    nombre_seguro = secure_filename(nombre_archivo)
    return send_from_directory(REPORTES_DIR, nombre_seguro, as_attachment=True)


@app.route("/api/catalogos", methods=["POST"])
def api_crear_catalogo():
    """Alta explicita de una drogueria, laboratorio o droga suelta,
    sin pasar por un producto."""
    datos = request.get_json(silent=True) or {}
    tipo = datos.get("tipo")
    nombre = (datos.get("nombre") or "").strip()
    contacto = (datos.get("contacto") or "").strip() or None

    if tipo not in ("drogueria", "laboratorio", "droga"):
        return jsonify({"ok": False, "errores": ["Tipo inválido."]}), 400
    if not nombre:
        return jsonify({"ok": False, "errores": ["Falta el nombre."]}), 400

    with BaseDatos() as db:
        if tipo == "drogueria":
            id_creado = db.crear_drogueria(nombre, contacto)
        elif tipo == "laboratorio":
            id_creado = db.crear_laboratorio(nombre)
        else:
            id_creado = db.crear_droga(nombre)

    if id_creado is None:
        etiquetas = {"drogueria": "una droguería", "laboratorio": "un laboratorio", "droga": "una droga"}
        return jsonify({"ok": False, "errores": [f"Ya existe {etiquetas[tipo]} con ese nombre."]}), 400

    return jsonify({"ok": True, "id": id_creado})


if __name__ == "__main__":
    app.run(debug=True)
