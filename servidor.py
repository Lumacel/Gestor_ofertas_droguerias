import os
import sys
import time
import logging
import threading
import webbrowser

import pystray
from pystray import MenuItem as Item
from PIL import Image, ImageDraw

from app import app


logger = logging.getLogger(__name__)

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 5000))

# Variable global para poder acceder al icono desde cualquier función
icono = None


def crear_icono(estado="verde"):
    """Crea un icono simple para la bandeja."""

    color = (0, 180, 0) if estado == "verde" else (200, 0, 0)

    imagen = Image.new("RGB", (64, 64), "white")
    dibujo = ImageDraw.Draw(imagen)

    dibujo.ellipse(
        (8, 8, 56, 56),
        fill=color
    )

    return imagen


def iniciar_flask():
    """Inicia Flask."""

    app.run(
        host=HOST,
        port=PORT,
        debug=False,
        use_reloader=False
    )


def abrir_aplicacion(icono, item):
    """Abre el navegador."""

    webbrowser.open(
        f"http://localhost:{PORT}"
    )


def salir(icono, item):
    """Cerrar desde el menú de la bandeja."""

    logger.info("Cerrando aplicación...")

    try:
        icono.stop()
    except Exception as e:
        logger.error(f"Error al detener icono: {e}")

    # Finalización inmediata
    os._exit(0)


def mostrar_mensaje_temporal(texto, segundos=3):
    try:
        from plyer import notification

        notification.notify(
            title="Servidor Flask",
            message=texto,
            timeout=segundos
        )
    except Exception as e:
        logger.warning(f"No se pudo mostrar notificación: {e}")


def iniciar_servidor():

    global icono

    # Hilo Flask
    servidor = threading.Thread(
        target=iniciar_flask,
        daemon=True
    )
    servidor.start()

    time.sleep(1)

    logger.info(
        f"Servidor escuchando en http://localhost:{PORT}"
    )

    menu = pystray.Menu(
        Item("Abrir aplicación", abrir_aplicacion),
        Item("Salir", salir)
    )

    icono = pystray.Icon(
        "GestorOfertas",
        crear_icono("verde"),
        "Gestor de Ofertas - Servidor activo",
        menu
    )

    mostrar_mensaje_temporal(
        f"Activo en puerto {PORT}",
        5
    )

    # Ejecutar pystray en hilo daemon
    tray_thread = threading.Thread(
        target=icono.run,
        daemon=True
    )
    tray_thread.start()

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:

        logger.info(
            "Ctrl+C detectado. Cerrando aplicación..."
        )

        try:
            icono.stop()
        except Exception:
            pass

        os._exit(0)


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    iniciar_servidor()