from base_datos import BaseDatos

with BaseDatos() as db:
    print("--- Tablas ---")
    for f in db._ejecutar(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
    ):
        print(f)

    print("\n--- Columnas de cada tabla ---")
    for f in db._ejecutar(
        "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' ORDER BY table_name, ordinal_position;"
    ):
        print(f)