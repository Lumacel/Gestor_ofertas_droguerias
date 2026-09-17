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

from datetime import date
from flask import Flask, render_template, request, jsonify
from base_datos import BaseDatos
app = Flask(__name__)


@app.route("/")
def index():
    return render_template("cargar_descuento.html")


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
    fecha_carga = datos.get("fecha_carga") or date.today().isoformat()
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
        id_creado = db.insertar_descuento(
            drogueria_id=drogueria_id,
            nivel_aplicacion=nivel_aplicacion,
            referencia_id=referencia_id,
            porcentaje=porcentaje,
            fecha_carga=fecha_carga,
            fecha_fin=fecha_fin,
            cantidad_minima=cantidad_minima,
        )

    return jsonify({"ok": True, "id": id_creado})


if __name__ == "__main__":
    app.run(debug=True)
