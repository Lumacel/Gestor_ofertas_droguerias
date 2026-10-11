from src.servidor import iniciar_servidor

import ctypes
import sys



if __name__ == "__main__":
    "Evita que se abra más de una instancia de la aplicación"
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "MiFlaskAppUnica")

    if ctypes.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        print("La aplicación ya está abierta.")
        sys.exit()

    iniciar_servidor()