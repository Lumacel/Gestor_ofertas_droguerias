"""
cargar_productos.py  (version definitiva)
==========================================
Dos mejoras sobre la version anterior:

1. VELOCIDAD: en vez de preguntarle a la base "existe este laboratorio?"
   una por una (miles de viajes de red), se resuelven TODOS los
   laboratorios y drogas nuevos en un par de operaciones masivas
   (execute_values), y los productos se insertan tambien en lote.

2. CRITERIO DE DUPLICADOS: cuando dos filas comparten el mismo codigo
   de barras, ya NO gana "la que aparece primero" -- gana la que NO
   es Droguer\u00eda del Sud (en cualquiera de sus variantes de escritura).
   Esa decision se toma ANTES de insertar, en Python, no dejando que
   la base descarte al azar por el UNIQUE constraint.
"""

import re
import pandas as pd
import psycopg2.extras
from base_datos import BaseDatos

RUTA_EXCEL = r"datos_excel\1980-2026_i_laboratorio_normalizado.xlsx"


def limpiar_codigo(v):
    """Convierte a texto plano y descarta codigos demasiado cortos
    para ser un codigo de barras real (1 o 2 cifras, como '0', '1',
    '23'). Un EAN valido tiene minimo 6-8 digitos."""
    if pd.isna(v):
        return None
    try:
        s = str(int(float(v))) if float(v).is_integer() else str(v)
    except (ValueError, TypeError):
        s = str(v).strip()
    s = s.strip()
    if not s or len(s) <= 2:
        return None
    return s


def es_drogueria_del_sud(laboratorio):
    """Detecta 'DROG.DEL SUD', 'DROG. DEL SUD', 'DROGUERIA DEL SUD',
    'DROG: DEL SUD', 'DROG DEL SUR', etc. -- tolera cualquier signo de
    puntuacion entre las palabras, sin confundir laboratorios reales
    que tambien contienen 'SUR' (ej. 'TACHA SUR')."""
    if not isinstance(laboratorio, str):
        return False
    t = laboratorio.upper()
    return bool(re.search(r"DROG\w*[^A-Z0-9]*DEL[^A-Z0-9]*SU[DR]\b", t))


def deduplicar_por_codigo(df):
    """De cada grupo de filas que comparten el mismo codigo de barras,
    se queda con UNA sola: preferentemente la que no es Drog. del Sud.
    Si ninguna de las dos lo es (o las dos lo son), gana la primera
    en orden de archivo -- ese caso ya vimos que es raro.

    Ademas, para CUALQUIER fila (gane o no la deduplicacion) donde el
    laboratorio declarado sea una variante de Drog. del Sud, se anula
    ese campo: Drog. del Sud es una drogueria, no un laboratorio
    fabricante, y no tiene que terminar creando una fila falsa en la
    tabla 'laboratorios'."""
    df = df.copy()
    df["_es_sud"] = df["laboratorio"].apply(es_drogueria_del_sud)
    df["_orden_original"] = range(len(df))

    con_codigo = df[df["codigo_limpio"].notna()].copy()
    sin_codigo = df[df["codigo_limpio"].isna()]

    # ordenar cada grupo para que la fila que NO es Drog.del Sud quede
    # primera (False < True al ordenar), y de haber empate, la que
    # aparecio antes en el archivo
    con_codigo = con_codigo.sort_values(["codigo_limpio", "_es_sud", "_orden_original"])
    ganadoras = con_codigo.drop_duplicates(subset=["codigo_limpio"], keep="first")

    resultado = pd.concat([ganadoras, sin_codigo]).sort_values("_orden_original")

    # en vez de anular el laboratorio en las filas de Drog. del Sud,
    # se le asigna un laboratorio placeholder 'DESCONOCIDO'. Esto deja
    # rastro (se puede filtrar despues con WHERE nombre='DESCONOCIDO'
    # para ir resolviendo el laboratorio real de a poco) en vez de
    # perder el dato con un NULL silencioso.
    resultado.loc[resultado["_es_sud"], "laboratorio"] = "DESCONOCIDO"

    return resultado.drop(columns=["_es_sud", "_orden_original"])


def resolver_ids_en_lote(cur, tabla, nombres):
    """Dado un conjunto de nombres (laboratorios o drogas), inserta
    los que no existan y devuelve un dict {nombre: id} con todos,
    en una sola operacion masiva en vez de una consulta por nombre."""
    nombres_unicos = sorted({n for n in nombres if pd.notna(n) and n})
    if not nombres_unicos:
        return {}
    filas = psycopg2.extras.execute_values(
        cur,
        f"""
        INSERT INTO {tabla} (nombre) VALUES %s
        ON CONFLICT (nombre) DO UPDATE SET nombre = EXCLUDED.nombre
        RETURNING id, nombre;
        """,
        [(n,) for n in nombres_unicos],
        fetch=True,
    )
    return {fila["nombre"]: fila["id"] for fila in filas}


def main():
    df = pd.read_excel(RUTA_EXCEL)
    df["codigo_limpio"] = df["codigo"].apply(limpiar_codigo)
    df["troquel_limpio"] = df["troquel"].apply(limpiar_codigo)
    df["laboratorio"] = df["laboratorio"].apply(lambda x: str(x).strip() if pd.notna(x) else None)
    df["droga"] = df["droga"].apply(lambda x: str(x).strip() if pd.notna(x) else None)
    df["producto"] = df["producto"].apply(lambda x: str(x).strip() if pd.notna(x) else None)

    df = df[df["producto"].notna() & (df["producto"] != "")]
    print(f"Filas con producto valido: {len(df)}")

    df = deduplicar_por_codigo(df)
    print(f"Filas despues de deduplicar por codigo: {len(df)}")

    with BaseDatos() as db:
        with db.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            print("Resolviendo laboratorios...")
            labs_id = resolver_ids_en_lote(cur, "laboratorios", df["laboratorio"])
            print(f"  {len(labs_id)} laboratorios")

            print("Resolviendo drogas...")
            drogas_id = resolver_ids_en_lote(cur, "drogas", df["droga"])
            print(f"  {len(drogas_id)} drogas")

            filas_productos = [
                (
                    fila["producto"],
                    fila["codigo_limpio"],
                    fila["troquel_limpio"],
                    labs_id.get(fila["laboratorio"]),
                    drogas_id.get(fila["droga"]),
                )
                for _, fila in df.iterrows()
            ]

            print(f"Insertando {len(filas_productos)} productos...")
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO productos (nombre, codigo, troquel, laboratorio_id, droga_id)
                VALUES %s
                ON CONFLICT DO NOTHING;
                """,
                filas_productos,
            )
            print(f"Filas afectadas: {cur.rowcount}")

    print("Listo.")


if __name__ == "__main__":
    main()
