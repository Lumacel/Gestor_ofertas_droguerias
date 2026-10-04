"""
basedatos.py
============
Adaptado al esquema real (ver estructura_base_datos.docx):

    laboratorios(id, nombre)
    drogas(id, nombre)
    droguerias(id, nombre, contacto)
    productos(id, nombre, codigo, troquel, laboratorio_id, droga_id)
    descuentos(id, drogueria_id, nivel_aplicacion, referencia_id,
               porcentaje, fecha_carga, fecha_fin)

Lo importante para entender las consultas de abajo: un descuento no
esta atado siempre a un producto. Segun 'nivel_aplicacion', referencia_id
puede ser el id de un producto, de una droga, de un laboratorio, o no
usarse en absoluto (nivel 'general' = aplica a todo lo de esa drogueria).
Por eso, para saber "que descuentos le tocan a este producto puntual"
hay que revisar los 4 caminos posibles, no solo un JOIN directo.
"""

import os
import re
import psycopg2
import psycopg2.extras
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


class BaseDatos:
    def __init__(self, database_url=None):
        self.database_url = database_url or os.environ["DATABASE_URL"]
        self.conn = None

    def __enter__(self):
        self.conn = psycopg2.connect(self.database_url)
        return self

    def __exit__(self, tipo_excepcion, valor_excepcion, traceback):
        if tipo_excepcion is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()
        return False

    def _ejecutar(self, consulta, parametros=()):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(consulta, parametros)
            # cur.description es None cuando la consulta no devuelve
            # filas (un UPDATE/DELETE sin RETURNING); pedir fetchall()
            # en ese caso rompe con "no results to fetch". Mejor
            # devolver una lista vacia que dejar explotar la app.
            if cur.description is None:
                return []
            return cur.fetchall()


    def buscar_ofertas(self, producto_id=None, codigo=None, troquel=None, nombre=None,
                        laboratorio=None, droga=None, drogueria=None,
                        porcentaje_minimo=None, solo_mejores=True, orden="porcentaje",
                        limite=100):
        """Busqueda combinada: cualquier filtro que venga en None se
        ignora, y los que si vienen se combinan con AND. producto_id
        es para cuando ya tenes el id a mano (ej. el usuario lo eligio
        de una lista) y no hace falta buscarlo de nuevo por texto;
        codigo/troquel se buscan exactos (son identificadores);
        nombre/laboratorio/droga/drogueria se buscan parciales (ILIKE);
        porcentaje_minimo filtra 'al menos este descuento', no un
        valor exacto.

        solo_mejores=True (por defecto) descarta las filas que perdieron
        frente a otra oferta para el mismo producto+drogueria -- para
        uso diario no interesa ver el descuento general si ya hay uno
        mejor por laboratorio para ese mismo producto. Con
        solo_mejores=False se ven todos los niveles que compiten, con
        'es_mejor' marcando cual gano -- util para auditar o depurar,
        como cuando cargamos un descuento de prueba para verificar la
        logica.

        orden="porcentaje" (por defecto) muestra primero las mejores
        ofertas, sin importar a que producto pertenecen. orden="nombre"
        agrupa todo por producto (alfabetico) y dentro de cada uno
        ordena por porcentaje -- util para comparar de un vistazo las
        distintas ofertas de un mismo producto entre si."""
        condiciones = ["(d.fecha_fin IS NULL OR d.fecha_fin >= CURRENT_DATE)"]
        parametros = []

        if producto_id:
            condiciones.append("p.id = %s")
            parametros.append(producto_id)
        if codigo:
            condiciones.append("p.codigo = %s")
            parametros.append(codigo)
        if troquel:
            condiciones.append("p.troquel = %s")
            parametros.append(troquel)
        if nombre:
            condiciones.append("p.nombre ILIKE %s")
            parametros.append(f"%{nombre}%")
        if laboratorio:
            condiciones.append("lab.nombre ILIKE %s")
            parametros.append(f"%{laboratorio}%")
        if droga:
            # exacta (sin %), para no traer combinaciones que solo
            # CONTIENEN la droga buscada (ej. "diclofenac+pridinol"
            # al buscar "diclofenac"). ILIKE sin comodines sigue
            # siendo insensible a mayusculas/minusculas.
            condiciones.append("dg.nombre ILIKE %s")
            parametros.append(droga)
        if drogueria:
            condiciones.append("dr.nombre ILIKE %s")
            parametros.append(f"%{drogueria}%")
        if porcentaje_minimo is not None:
            condiciones.append("d.porcentaje >= %s")
            parametros.append(porcentaje_minimo)

        consulta = f"""
            WITH resultados AS (
                SELECT p.id AS producto_id, p.nombre AS producto, p.codigo, p.troquel,
                       lab.nombre AS laboratorio, dg.nombre AS droga,
                       dr.nombre AS drogueria, d.nivel_aplicacion, d.porcentaje,
                       d.cantidad_minima, d.fecha_carga, d.fecha_fin,
                       RANK() OVER (
                           PARTITION BY p.id, d.drogueria_id
                           ORDER BY d.porcentaje DESC
                       ) = 1 AS es_mejor
                FROM productos p
                LEFT JOIN laboratorios lab ON lab.id = p.laboratorio_id
                LEFT JOIN drogas dg ON dg.id = p.droga_id
                JOIN descuentos d ON (
                       (d.nivel_aplicacion = 'producto'    AND d.referencia_id = p.id)
                    OR (d.nivel_aplicacion = 'droga'        AND d.referencia_id = p.droga_id)
                    OR (d.nivel_aplicacion = 'laboratorio'  AND d.referencia_id = p.laboratorio_id)
                    OR (d.nivel_aplicacion = 'general')
                )
                JOIN droguerias dr ON dr.id = d.drogueria_id
                WHERE {" AND ".join(condiciones)}
            )
            SELECT * FROM resultados
            {"WHERE es_mejor" if solo_mejores else ""}
            ORDER BY {"producto, porcentaje DESC" if orden == "nombre" else "porcentaje DESC, producto"}
            LIMIT %s;
        """
        parametros.append(limite)
        return self._ejecutar(consulta, tuple(parametros))


    # -----------------------------------------------------------------
    # Carga: resolver laboratorio/droga y crear el producto
    # -----------------------------------------------------------------

    def obtener_o_crear_laboratorio(self, nombre):
        return self._obtener_o_crear("laboratorios", nombre)

    def obtener_o_crear_droga(self, nombre):
        return self._obtener_o_crear("drogas", nombre)

    def obtener_o_crear_drogueria(self, nombre):
        """Igual que obtener_o_crear_laboratorio/droga, pero ademas
        sube el nombre a mayusculas antes de guardar (ej. 'liek' se
        guarda como 'LIEK'), para que no convivan variantes distintas
        de la misma drogueria por como la escribio cada excel."""
        if not nombre:
            return None
        nombre_mayus = str(nombre).strip().upper()
        if not nombre_mayus:
            return None
        return self._obtener_o_crear("droguerias", nombre_mayus)

    def _obtener_o_crear(self, tabla, nombre):
        """Inserta 'nombre' en la tabla si no existe, y devuelve su id
        en cualquier caso (exista ya o se acabe de crear). El truco es
        el 'ON CONFLICT ... DO UPDATE': si el nombre ya existe, en vez
        de fallar por la restriccion UNIQUE, lo 'actualiza' con el
        mismo valor -- lo cual no cambia nada, pero permite que el
        RETURNING siempre traiga el id, se haya insertado o no."""
        if nombre is None or (isinstance(nombre, float) and nombre != nombre):  # NaN
            return None
        nombre_limpio = str(nombre).strip()
        if not nombre_limpio:
            return None
        assert tabla in ("laboratorios", "drogas", "droguerias")  # nunca interpolar tabla libre
        consulta = f"""
            INSERT INTO {tabla} (nombre) VALUES (%s)
            ON CONFLICT (nombre) DO UPDATE SET nombre = EXCLUDED.nombre
            RETURNING id;
        """
        resultado = self._ejecutar(consulta, (nombre_limpio,))
        return resultado[0]["id"] if resultado else None

    def insertar_producto_si_no_existe(self, nombre, codigo, troquel, laboratorio_id, droga_id):
        """Inserta el producto. Si ya existe uno con el mismo codigo o
        el mismo troquel (las dos columnas UNIQUE de la tabla), no
        rompe ni duplica: simplemente no hace nada, gracias a
        'ON CONFLICT DO NOTHING' sin especificar columna -- eso hace
        que aplique ante CUALQUIER restriccion unica que se pise."""
        consulta = """
            INSERT INTO productos (nombre, codigo, troquel, laboratorio_id, droga_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id;
        """
        resultado = self._ejecutar(consulta, (nombre, codigo, troquel, laboratorio_id, droga_id))
        return resultado[0]["id"] if resultado else None

    # -----------------------------------------------------------------
    # Alta explicita de droguerias/laboratorios/drogas sueltos
    # -----------------------------------------------------------------
    # A diferencia de obtener_o_crear_* (que resuelve en silencio si ya
    # existe, pensado para la carga de productos), estos metodos son
    # para cuando el usuario quiere dar de alta algo puntualmente y le
    # interesa saber si ya existia -- por eso NO hacen upsert, devuelven
    # None si hubo conflicto para que la pantalla le avise "ya existe".

    def crear_drogueria(self, nombre, contacto=None):
        nombre = str(nombre).strip().upper() if nombre else nombre
        consulta = """
            INSERT INTO droguerias (nombre, contacto)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id;
        """
        resultado = self._ejecutar(consulta, (nombre, contacto))
        return resultado[0]["id"] if resultado else None

    def crear_laboratorio(self, nombre):
        consulta = """
            INSERT INTO laboratorios (nombre) VALUES (%s)
            ON CONFLICT DO NOTHING
            RETURNING id;
        """
        resultado = self._ejecutar(consulta, (nombre,))
        return resultado[0]["id"] if resultado else None

    def crear_droga(self, nombre):
        consulta = """
            INSERT INTO drogas (nombre) VALUES (%s)
            ON CONFLICT DO NOTHING
            RETURNING id;
        """
        resultado = self._ejecutar(consulta, (nombre,))
        return resultado[0]["id"] if resultado else None

    # -----------------------------------------------------------------
    # Busqueda generica de entidades (para autocompletar en la web)
    # -----------------------------------------------------------------

    def buscar_entidad(self, tabla, texto, limite=20):
        """Busca por nombre en 'productos', 'drogas', 'laboratorios' o
        'droguerias'. 'tabla' viene siempre de una lista fija (nunca
        de texto libre del usuario), por eso es seguro interpolarla."""
        assert tabla in ("productos", "drogas", "laboratorios", "droguerias")
        consulta = f"""
            SELECT id, nombre
            FROM {tabla}
            WHERE nombre ILIKE %s
            ORDER BY nombre
            LIMIT %s;
        """
        return self._ejecutar(consulta, (f"%{texto}%", limite))

    def encontrar_producto(self, nombre=None, codigo=None, troquel=None):
        """Busca un producto ya existente para asociarle un descuento.
        Prioridad: troquel exacto, despues codigo de barras exacto,
        y recien si ninguno matchea, nombre parecido por similitud de
        trigramas (pg_trgm) en vez de substring exacto -- tolera orden
        de palabras distinto y variaciones chicas de redaccion.
        Devuelve el id, o None si no lo encontro por ningun camino --
        nunca crea un producto nuevo (a diferencia de laboratorio/
        droga, un producto necesita mas datos que una fila de
        descuento)."""
        if troquel:
            r = self._ejecutar("SELECT id FROM productos WHERE troquel = %s LIMIT 1;", (troquel,))
            if r:
                return r[0]["id"]
        if codigo:
            r = self._ejecutar("SELECT id FROM productos WHERE codigo = %s LIMIT 1;", (codigo,))
            if r:
                return r[0]["id"]
        if nombre:
            # similitud por trigramas (pg_trgm), no substring exacto:
            # tolera orden de palabras distinto y variaciones chicas
            # de redaccion (ej. "AEROGAL aerosol x 170 g" vs
            # "AEROGAL AEROSOL X 170 GR."). El operador %% ya descarta
            # solo los resultados demasiado distintos.
            r = self._ejecutar(
                """
                SELECT id, nombre AS nombre_candidato, similarity(nombre, %s) AS score
                FROM productos
                WHERE nombre %% %s
                ORDER BY score DESC
                LIMIT 5;
                """,
                (nombre, nombre),
            )
            UMBRAL_SIMILITUD = 0.65  # por debajo de esto, mejor no adivinar
            numeros_buscado = re.findall(r"\d+(?:\.\d+)?", nombre)
            for fila in r:
                if fila["score"] < UMBRAL_SIMILITUD:
                    break  # vienen ordenados por score: si este no alcanza, ninguno de los siguientes tampoco
                numeros_candidato = re.findall(r"\d+(?:\.\d+)?", fila["nombre_candidato"])

                if numeros_buscado:
                    if not all(n in numeros_candidato for n in numeros_buscado):
                        continue

                return fila["id"]
        return None

    # -----------------------------------------------------------------
    # Carga de descuentos
    # -----------------------------------------------------------------

    def insertar_descuento(self, drogueria_id, nivel_aplicacion, referencia_id,
                            porcentaje, fecha_carga, fecha_fin, cantidad_minima):
        """Guarda un descuento evitando que las ofertas sin vencimiento
        se acumulen para siempre. Antes de insertar, busca si ya hay
        una fila VIGENTE para la misma combinacion (drogueria + nivel +
        a que aplica):

          - Mismo valor (igual porcentaje y cantidad_minima) -> no hace
            nada, insertar de nuevo seria puro ruido.
          - Misma fecha_carga que la vigente (se cargo dos veces el
            mismo dia) -> la actualiza en el lugar en vez de duplicar.
          - Fecha distinta y el valor cambio -> cierra la anterior
            (fecha_fin = el dia antes de que arranque la nueva) e
            inserta la nueva, para que quede un historial real sin dos
            filas vigentes a la vez para lo mismo.

        Devuelve (id, estado), con estado en
        'creado' | 'sin_cambios' | 'actualizado' | 'reemplazado'.
        """
        existente = self._ejecutar(
            """
            SELECT id, porcentaje, cantidad_minima, fecha_carga, fecha_fin
            FROM descuentos
            WHERE drogueria_id = %s
              AND nivel_aplicacion = %s
              AND referencia_id IS NOT DISTINCT FROM %s
              AND (fecha_fin IS NULL OR fecha_fin >= CURRENT_DATE)
            ORDER BY fecha_carga DESC
            LIMIT 1;
            """,
            (drogueria_id, nivel_aplicacion, referencia_id),
        )

        if existente:
            fila = existente[0]
            # cantidad_minima es un dato secundario: no participa en
            # identificar si es "la misma oferta", pero si cambia se
            # considera un cambio de valor igual que el porcentaje
            mismo_valor = (
                float(fila["porcentaje"]) == float(porcentaje)
                and (fila["cantidad_minima"] or None) == (cantidad_minima or None)
            )
            mismo_vencimiento = (
                (str(fila["fecha_fin"]) if fila["fecha_fin"] else None)
                == (str(fecha_fin) if fecha_fin else None)
            )
            if mismo_valor and mismo_vencimiento:
                return fila["id"], "sin_cambios"

            # mismo valor pero otro vencimiento, o carga del mismo dia:
            # es la misma oferta, se actualiza en el lugar
            if mismo_valor or str(fila["fecha_carga"]) == str(fecha_carga):
                resultado = self._ejecutar(
                    """
                    UPDATE descuentos
                    SET porcentaje = %s, cantidad_minima = %s, fecha_fin = %s
                    WHERE id = %s
                    RETURNING id;
                    """,
                    (porcentaje, cantidad_minima, fecha_fin, fila["id"]),
                )
                return resultado[0]["id"], "actualizado"

            # fecha distinta y el valor cambio: cerrar la anterior el
            # dia antes de que arranque la nueva
            self._ejecutar(
                """
                UPDATE descuentos
                SET fecha_fin = (%s::date - INTERVAL '1 day')::date
                WHERE id = %s
                RETURNING id;
                """,
                (fecha_carga, fila["id"]),
            )

        consulta = """
            INSERT INTO descuentos
                (drogueria_id, nivel_aplicacion, referencia_id, porcentaje,
                 fecha_carga, fecha_fin, cantidad_minima)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """
        resultado = self._ejecutar(consulta, (
            drogueria_id, nivel_aplicacion, referencia_id, porcentaje,
            fecha_carga, fecha_fin, cantidad_minima,
        ))
        id_nuevo = resultado[0]["id"] if resultado else None
        return id_nuevo, ("reemplazado" if existente else "creado")
