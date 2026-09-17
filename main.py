"""
main.py
=======
Punto de entrada para correr consultas contra la base. La conexion
se abre y se cierra sola gracias a BaseDatos (ver basedatos.py) --
aca solo nos ocupamos de QUE preguntar, no de administrar la conexion.
"""

from app import app
from base_datos import BaseDatos
from pprint import pprint

def main():
 
    with BaseDatos() as db:
    
        #print("--- Busqueda por nombre: 'actron' ---")
        #for fila in db.buscar_por_nombre("actron",10):
        #   print(fila)

        #print("\n--- Busqueda por monodroga: 'memantine' ---")
        #for fila in db.buscar_por_monodroga("memantine",10):
        #   print(fila)

        #print("\n--- Busqueda de descuentos por droga : 'diclofenac potasico' ---")
        #for fila in db.buscar_descuentos_por_droga("diclofenac potasico"):
         #   print(fila)

        #print("\n--- Top 10 descuentos vigentes ---")
        #for fila in db.ranking_top_descuentos(limite=10):
        #    print(fila)

        #print("\n--- Top 10 descuentos vigentes ---")
        #for fila in db.ranking_top_descuentos(limite=10):
        #   print(fila)

        print("\n--- Ofertas por drogueria y porcentaje ---")
        for fila in db.buscar_ofertas(droga="diclofenac", nombre="rodin", porcentaje_minimo=20):
            print('producto:',fila['producto'], "droga:", fila['droga'], "laboratorio:", fila['laboratorio'], "descuento:", fila['porcentaje'], "drogueria:", fila['drogueria'])

    # aca afuera del "with", la conexion ya se cerro sola --
    # no hace falta llamar nada mas.
    


if __name__ == "__main__":
    #main()
    app.run(host="0.0.0.0", port=5000, debug=True)