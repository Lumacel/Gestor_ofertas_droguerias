import threading
import time
import webbrowser
import logging
import os
import pystray
from PIL import Image, ImageDraw
from pystray import MenuItem as Item

from app import app


logger = logging.getLogger(__name__)


HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 5000))


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
    """Inicia el servidor Flask."""

    app.run(
        host=HOST,
        port=PORT,
        debug=False,
        use_reloader=False
    )


def abrir_aplicacion(icono, item):
    webbrowser.open(f"http://localhost:{PORT}")


def salir(icono, item):
    logger.info("Cerrando aplicación...")
    icono.stop()


def mostrar_mensaje_temporal(texto, segundos=3):
    from plyer import notification

    notification.notify(
        title="Servidor Flask",
        message=texto,
        timeout=segundos
    )


def iniciar_servidor():

    servidor = threading.Thread(
        target=iniciar_flask,
        daemon=True
    )

    servidor.start()

    time.sleep(1)

    logger.info(
        "Servidor escuchando en http://%s:%s",
        HOST,
        PORT
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
        f"Activo en puerto {PORT}",5
    )

    icono.run()


if __name__ == "__main__":
    iniciar_servidor()