#!/usr/bin/env python3
import os
import json
import shutil
import asyncio
import uuid
import hashlib
import secrets
from urllib.parse import quote
import tkinter as tk
from tkinter import filedialog
import flet as ft

# ---------------------------------------------------------------------------
# Persistencia y Carpetas
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "propiedades.json")
USERS_FILE = os.path.join(BASE_DIR, "usuarios.json")
PHOTOS_DIR = os.path.join(BASE_DIR, "fotos")
os.makedirs(PHOTOS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Paletas de colores (claro / oscuro)
# ---------------------------------------------------------------------------
LIGHT_PALETTE = {
    "INK": "#01040C",
    "INK_SOFT": "#5E594F",
    "PAPER": "#F6FAF4",
    "PAPER_2": "#F0E9DC",
    "SURFACE": "#FFFFFF",
}
DARK_PALETTE = {
    "INK": "#F4F1EA",
    "INK_SOFT": "#A29C8E",
    "PAPER": "#14160F",
    "PAPER_2": "#2A2C23",
    "SURFACE": "#1E2018",
}

# Colores que no cambian con el tema (acentos de marca y elementos de
# contraste fijo, como los íconos sobre las fotos).
VERDIGRIS = "#2F6F62"
BRASS = "#C08B3D"
WHITE = "#FFFFFF"
# Botones de acción primaria (fondo oscuro + texto claro) mantienen su
# identidad visual en ambos temas.
ACTION_BG = "#01040C"
ACTION_TEXT = "#F4F6F6"

# Variables de color "activas": arrancan con la paleta clara y se
# reasignan al alternar el tema.
INK = LIGHT_PALETTE["INK"]
INK_SOFT = LIGHT_PALETTE["INK_SOFT"]
PAPER = LIGHT_PALETTE["PAPER"]
PAPER_2 = LIGHT_PALETTE["PAPER_2"]
SURFACE = LIGHT_PALETTE["SURFACE"]


def load_properties():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

        changed = False
        for item in data:
            if "id" not in item:
                item["id"] = str(uuid.uuid4())
                changed = True
            # Migración: "foto" (única, versión vieja) -> "fotos" (lista)
            if "fotos" not in item:
                foto_vieja = item.get("foto")
                item["fotos"] = [foto_vieja] if foto_vieja else []
                changed = True
            if "favorito" not in item:
                item["favorito"] = False
                changed = True
            if "direccion" not in item:
                item["direccion"] = ""
                changed = True
            if "contacto" not in item:
                item["contacto"] = ""
                changed = True
            if "email" not in item:
                item["email"] = ""
                changed = True
            # Migración: propiedades viejas no tienen dueño asignado.
            # Quedan "sin dueño" hasta que un admin las reclame o edite.
            if "propietario_id" not in item:
                item["propietario_id"] = ""
                changed = True
            if "propietario_nombre" not in item:
                item["propietario_nombre"] = ""
                changed = True
        if changed:
            save_properties(data)
        return data
    return []


def save_properties(properties_list):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(properties_list, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def currency(n):
    return "$" + f"{n:,.0f}".replace(",", ".")


# ---------------------------------------------------------------------------
# Usuarios y autenticación
# ---------------------------------------------------------------------------
def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_users(users_list):
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users_list, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000
    ).hex()


def verify_password(password, salt, stored_hash):
    return hash_password(password, salt) == stored_hash


# ---------------------------------------------------------------------------
# Helper de compatibilidad para alignment entre versiones de Flet
# ---------------------------------------------------------------------------
def _center_alignment():
    """Devuelve el valor de alineación 'centro' sin importar la versión de
    Flet instalada. Versiones nuevas movieron esto de ft.alignment.center a
    ft.Alignment.CENTER; este helper prueba ambas para que el programa no
    se rompa por un cambio de API."""
    new_api = getattr(ft, "Alignment", None)
    if new_api is not None and hasattr(new_api, "CENTER"):
        return new_api.CENTER
    old_api = getattr(ft, "alignment", None)
    if old_api is not None and hasattr(old_api, "center"):
        return old_api.center
    return None


# ---------------------------------------------------------------------------
# Aplicación Principal en Flet
# ---------------------------------------------------------------------------
def main(page: ft.Page):
    page.title = "Qiti-Depp"
    page.bgcolor = PAPER
    page.padding = 24
    page.theme_mode = ft.ThemeMode.LIGHT

    properties = load_properties()
    users = load_users()

    state = {
        "active_type": "todos",
        "search_text": "",
        "sort_value": "Más recientes",
        "solo_favoritos": False,
        "precio_min": "",
        "precio_max": "",
        "current_user": None,  # {"id":..., "username":..., "es_admin": bool}
        "theme": "light",
    }

    galeria_grid = ft.GridView(
        expand=True,
        runs_count=3,
        max_extent=320,
        child_aspect_ratio=0.75,
        spacing=20,
        run_spacing=20,
    )

    result_label = ft.Text(
        "0 propiedades disponibles", size=13, color=INK_SOFT, weight=ft.FontWeight.W_500
    )

    def puede_gestionar(item):
        """Devuelve True si el usuario actual puede editar/eliminar esta propiedad."""
        user = state["current_user"]
        if not user:
            return False
        if user.get("es_admin"):
            return True
        return item.get("propietario_id") == user["id"]

    # ------------------------------------------------------------------
    # Selección de fotos (soporta múltiples archivos)
    # ------------------------------------------------------------------
    def _abrir_dialogo_tkinter_multiple():
        """Corre el selector de archivos nativo de tkinter permitiendo elegir
        varias fotos a la vez. Se ejecuta en un hilo aparte para no bloquear
        el loop de eventos de Flet."""
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        rutas = filedialog.askopenfilenames(
            title="Seleccionar Fotos",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp *.gif"), ("Todos los archivos", "*.*")],
        )
        root.destroy()
        return list(rutas)

    # ------------------------------------------------------------------
    # Borrado de propiedades (con confirmación)
    # ------------------------------------------------------------------
    def pedir_confirmacion_borrado(item):
        if not puede_gestionar(item):
            page.snack_bar = ft.SnackBar(
                content=ft.Text("No tenés permiso para eliminar esta propiedad."), open=True
            )
            page.update()
            return

        def cerrar_confirmacion(_):
            confirm_dialog.open = False
            page.update()

        def confirmar_borrado(_):
            if not puede_gestionar(item):
                confirm_dialog.open = False
                page.update()
                return
            properties[:] = [p for p in properties if p.get("id") != item.get("id")]
            save_properties(properties)
            confirm_dialog.open = False
            page.update()
            render()

        confirm_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("¿Eliminar propiedad?", weight=ft.FontWeight.BOLD, color=INK),
            content=ft.Text(
                f"Esta acción no se puede deshacer. Se eliminará "
                f"\"{item.get('titulo', 'esta propiedad')}\"."
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=cerrar_confirmacion),
                ft.ElevatedButton(
                    "Eliminar", bgcolor="#C0392B", color=WHITE, on_click=confirmar_borrado
                ),
            ],
        )
        page.overlay.append(confirm_dialog)
        page.dialog = confirm_dialog
        confirm_dialog.open = True
        page.update()

    # ------------------------------------------------------------------
    # Favoritos
    # ------------------------------------------------------------------
    def toggle_favorito(item):
        item["favorito"] = not item.get("favorito", False)
        save_properties(properties)
        render()

    def toggle_filtro_favoritos(e):
        state["solo_favoritos"] = not state["solo_favoritos"]
        btn_favoritos_filter.icon = ft.Icons.STAR if state["solo_favoritos"] else ft.Icons.STAR_BORDER
        btn_favoritos_filter.icon_color = BRASS if state["solo_favoritos"] else INK_SOFT
        render()

    btn_favoritos_filter = ft.IconButton(
        icon=ft.Icons.STAR_BORDER,
        icon_color=INK_SOFT,
        tooltip="Ver solo favoritos",
        on_click=toggle_filtro_favoritos,
    )

    # ------------------------------------------------------------------
    # Galería de fotos
    # ------------------------------------------------------------------
    def abrir_galeria(item):
        fotos = [f for f in item.get("fotos", []) if f and os.path.exists(f)]

        def cerrar(_):
            galeria_dialog.open = False
            page.update()

        if fotos:
            contenido = ft.Row(
                controls=[
                    ft.Image(src=f, width=260, height=200, fit=ft.BoxFit.COVER, border_radius=8)
                    for f in fotos
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            )
        else:
            contenido = ft.Text("No hay fotos cargadas para esta propiedad.", color=INK_SOFT)

        galeria_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(item.get("titulo", "Fotos"), weight=ft.FontWeight.BOLD, color=INK),
            content=contenido,
            actions=[ft.TextButton("Cerrar", on_click=cerrar)],
        )
        page.overlay.append(galeria_dialog)
        page.dialog = galeria_dialog
        galeria_dialog.open = True
        page.update()

    # ------------------------------------------------------------------
    # Contacto con el propietario
    # ------------------------------------------------------------------
    def _limpiar_telefono(numero):
        numero = numero.strip()
        return "".join(ch for ch in numero if ch.isdigit())

    def abrir_dialogo_contacto(item):
        telefono = item.get("contacto", "")
        email = item.get("email", "")
        titulo_prop = item.get("titulo", "esta propiedad")

        def cerrar(_):
            contacto_dialog.open = False
            page.update()

        def mostrar_aviso_copiado(texto):
            page.snack_bar = ft.SnackBar(content=ft.Text(f"Copiado: {texto}"), open=True)
            page.update()

        def copiar_telefono(_):
            page.set_clipboard(telefono.strip())
            mostrar_aviso_copiado(telefono.strip())

        def copiar_email(_):
            page.set_clipboard(email.strip())
            mostrar_aviso_copiado(email.strip())

        acciones_contacto = []
        info_controles = []

        if telefono:
            numero_limpio = _limpiar_telefono(telefono)
            mensaje = f"Hola! Te escribo por la propiedad \"{titulo_prop}\" que vi en Llave."
            url_whatsapp = f"https://wa.me/{numero_limpio}?text={quote(mensaje)}"

            info_controles.append(
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.PHONE, color=INK_SOFT, size=16),
                        ft.Text(telefono, size=13, color=INK),
                    ],
                    spacing=6,
                )
            )
            acciones_contacto.append(
                ft.ElevatedButton(
                    "WhatsApp",
                    icon=ft.Icons.CHAT,
                    bgcolor=VERDIGRIS,
                    color=WHITE,
                    url=url_whatsapp,
                )
            )
            acciones_contacto.append(
                ft.TextButton("Copiar número", icon=ft.Icons.COPY, on_click=copiar_telefono)
            )

        if email:
            asunto = f"Consulta sobre {titulo_prop}"
            cuerpo = f"Hola, estoy interesado/a en la propiedad \"{titulo_prop}\"."
            url_gmail = (
                "https://mail.google.com/mail/?view=cm&fs=1"
                f"&to={quote(email.strip())}&su={quote(asunto)}&body={quote(cuerpo)}"
            )

            info_controles.append(
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.EMAIL, color=INK_SOFT, size=16),
                        ft.Text(email, size=13, color=INK),
                    ],
                    spacing=6,
                )
            )
            acciones_contacto.append(
                ft.ElevatedButton(
                    "Enviar por Gmail",
                    icon=ft.Icons.ALTERNATE_EMAIL,
                    bgcolor=BRASS,
                    color=WHITE,
                    url=url_gmail,
                )
            )
            acciones_contacto.append(
                ft.TextButton("Copiar email", icon=ft.Icons.COPY, on_click=copiar_email)
            )

        if not telefono and not email:
            contenido = ft.Text(
                "El propietario no cargó datos de contacto para esta propiedad.",
                size=13,
                color=INK_SOFT,
            )
        else:
            contenido = ft.Column(
                tight=True,
                spacing=14,
                controls=[
                    *info_controles,
                    ft.Row(controls=acciones_contacto, spacing=10, wrap=True),
                ],
            )

        contacto_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Contactar por \"{titulo_prop}\"", weight=ft.FontWeight.BOLD, color=INK),
            content=contenido,
            actions=[ft.TextButton("Cerrar", on_click=cerrar)],
        )
        page.overlay.append(contacto_dialog)
        page.dialog = contacto_dialog
        contacto_dialog.open = True
        page.update()

    # ------------------------------------------------------------------
    # Función de Renderizado / Filtrado
    # ------------------------------------------------------------------
    def render():
        galeria_grid.controls.clear()

        filtered = list(properties)

        if state["active_type"] != "todos":
            filtered = [p for p in filtered if p.get("tipo") == state["active_type"]]

        if state["search_text"]:
            search = state["search_text"].lower()
            filtered = [
                p
                for p in filtered
                if search in p.get("titulo", "").lower()
                or search in p.get("descripcion", "").lower()
            ]

        if state["precio_min"]:
            try:
                pmin = float(str(state["precio_min"]).replace(",", "."))
                filtered = [p for p in filtered if float(p.get("precio", 0)) >= pmin]
            except ValueError:
                pass

        if state["precio_max"]:
            try:
                pmax = float(str(state["precio_max"]).replace(",", "."))
                filtered = [p for p in filtered if float(p.get("precio", 0)) <= pmax]
            except ValueError:
                pass

        if state["solo_favoritos"]:
            filtered = [p for p in filtered if p.get("favorito")]

        if state["sort_value"] == "Precio: menor a mayor":
            filtered.sort(key=lambda x: float(x.get("precio", 0)))
        elif state["sort_value"] == "Precio: mayor a menor":
            filtered.sort(key=lambda x: float(x.get("precio", 0)), reverse=True)
        elif state["sort_value"] == "Más recientes":
            filtered = list(reversed(filtered))

        result_label.value = f"{len(filtered)} propiedades disponibles"
        result_label.color = INK_SOFT

        for item in filtered:
            fotos = item.get("fotos", [])
            primera_foto = next((f for f in fotos if f and os.path.exists(f)), None)
            img_src = primera_foto if primera_foto else "https://picsum.photos/400/300"
            es_favorito = item.get("favorito", False)
            es_propietario = puede_gestionar(item)

            info_controles = [
                ft.Text(
                    item.get("tipo", "Propiedad").upper(),
                    size=11,
                    color=BRASS,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    item.get("titulo", "Sin título"),
                    size=16,
                    color=INK,
                    weight=ft.FontWeight.BOLD,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                ft.Text(
                    currency(float(item.get("precio", 0))),
                    size=15,
                    color=VERDIGRIS,
                    weight=ft.FontWeight.W_600,
                ),
                ft.Text(
                    item.get("descripcion", ""),
                    size=12,
                    color=INK_SOFT,
                    max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
            ]

            if item.get("propietario_nombre"):
                info_controles.append(
                    ft.Text(
                        f"Publicado por {item['propietario_nombre']}",
                        size=10,
                        color=INK_SOFT,
                        italic=True,
                    )
                )

            if item.get("direccion"):
                info_controles.append(
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.LOCATION_ON, color=INK_SOFT, size=13),
                            ft.Text(
                                item["direccion"],
                                size=11,
                                color=INK_SOFT,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                expand=True,
                            ),
                        ],
                        spacing=4,
                    )
                )
                url_maps = f"https://www.google.com/maps/search/?api=1&query={quote(item['direccion'])}"
                info_controles.append(
                    ft.TextButton(
                        "Ver en el mapa",
                        icon=ft.Icons.MAP,
                        style=ft.ButtonStyle(padding=0),
                        url=url_maps,
                    )
                )

            if len(fotos) > 1:
                info_controles.append(
                    ft.TextButton(
                        f"Ver fotos ({len(fotos)})",
                        icon=ft.Icons.PHOTO_LIBRARY,
                        style=ft.ButtonStyle(padding=0),
                        on_click=lambda e, it=item: abrir_galeria(it),
                    )
                )

            info_controles.append(
                ft.ElevatedButton(
                    "Contactar propietario",
                    icon=ft.Icons.CHAT_BUBBLE_OUTLINE,
                    bgcolor=ACTION_BG,
                    color=ACTION_TEXT,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=6)),
                    on_click=lambda e, it=item: abrir_dialogo_contacto(it),
                )
            )

            stack_controls = [
                ft.Image(
                    src=img_src,
                    height=160,
                    fit=ft.BoxFit.COVER,
                    border_radius=ft.BorderRadius.only(top_left=12, top_right=12),
                ),
                ft.Container(
                    top=8,
                    left=8,
                    content=ft.IconButton(
                        icon=ft.Icons.STAR if es_favorito else ft.Icons.STAR_BORDER,
                        icon_color=BRASS if es_favorito else WHITE,
                        bgcolor="#90201F1D",
                        icon_size=18,
                        tooltip="Marcar como favorito",
                        on_click=lambda e, it=item: toggle_favorito(it),
                    ),
                ),
            ]

            # Los botones de editar/eliminar solo se muestran si el usuario
            # actual es el dueño de la propiedad (o es admin).
            if es_propietario:
                stack_controls.append(
                    ft.Container(
                        top=8,
                        right=8,
                        content=ft.Row(
                            spacing=4,
                            controls=[
                                ft.IconButton(
                                    icon=ft.Icons.EDIT,
                                    icon_color=WHITE,
                                    bgcolor="#90201F1D",
                                    icon_size=18,
                                    tooltip="Editar propiedad",
                                    on_click=lambda e, it=item: open_property_dialog(it),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.DELETE,
                                    icon_color=WHITE,
                                    bgcolor="#90201F1D",
                                    icon_size=18,
                                    tooltip="Eliminar propiedad",
                                    on_click=lambda e, it=item: pedir_confirmacion_borrado(it),
                                ),
                            ],
                        ),
                    )
                )

            card = ft.Container(
                bgcolor=SURFACE,
                border_radius=12,
                shadow=ft.BoxShadow(blur_radius=8, color="#10000000"),
                content=ft.Column(
                    controls=[
                        ft.Stack(controls=stack_controls),
                        ft.Container(
                            padding=12,
                            content=ft.Column(spacing=4, controls=info_controles),
                        ),
                    ]
                ),
            )
            galeria_grid.controls.append(card)

        page.update()

    # ------------------------------------------------------------------
    # Diálogo para publicar / editar propiedades (Formulario)
    # ------------------------------------------------------------------
    def open_property_dialog(item=None):
        es_edicion = item is not None

        if es_edicion and not puede_gestionar(item):
            page.snack_bar = ft.SnackBar(
                content=ft.Text("No tenés permiso para editar esta propiedad."), open=True
            )
            page.update()
            return

        fotos_temp = list(item.get("fotos", [])) if item else []

        txt_titulo = ft.TextField(
            label="Título", value=item.get("titulo", "") if item else "", border_color=INK_SOFT
        )
        txt_precio = ft.TextField(
            label="Precio ($)",
            value=str(item.get("precio", "")) if item else "",
            keyboard_type=ft.KeyboardType.NUMBER,
            border_color=INK_SOFT,
        )
        txt_desc = ft.TextField(
            label="Descripción",
            value=item.get("descripcion", "") if item else "",
            multiline=True,
            border_color=INK_SOFT,
        )
        txt_direccion = ft.TextField(
            label="Dirección (opcional)",
            hint_text="Ej: Av. Corrientes 1234, CABA",
            value=item.get("direccion", "") if item else "",
            border_color=INK_SOFT,
        )
        txt_contacto = ft.TextField(
            label="Teléfono / WhatsApp del propietario",
            hint_text="Ej: +54 9 11 1234-5678",
            value=item.get("contacto", "") if item else "",
            border_color=INK_SOFT,
        )
        txt_email = ft.TextField(
            label="Email de contacto (opcional)",
            value=item.get("email", "") if item else "",
            border_color=INK_SOFT,
        )

        drop_tipo = ft.Dropdown(
            label="Tipo de propiedad",
            value=item.get("tipo") if item else None,
            options=[
                ft.DropdownOption("Departamento"),
                ft.DropdownOption("Casa"),
                ft.DropdownOption("Local"),
            ],
            border_color=INK_SOFT,
        )

        error_text = ft.Text("", size=12, color="#C0392B")
        fotos_preview_row = ft.Row(spacing=8, wrap=True)

        def refrescar_preview():
            fotos_preview_row.controls.clear()
            for ruta in fotos_temp:
                fotos_preview_row.controls.append(
                    ft.Stack(
                        controls=[
                            ft.Image(
                                src=ruta, width=70, height=70, fit=ft.BoxFit.COVER, border_radius=8
                            ),
                            ft.Container(
                                top=-6,
                                right=-6,
                                content=ft.IconButton(
                                    icon=ft.Icons.CANCEL,
                                    icon_color="#C0392B",
                                    icon_size=18,
                                    tooltip="Quitar foto",
                                    on_click=lambda e, r=ruta: quitar_foto(r),
                                ),
                            ),
                        ]
                    )
                )
            page.update()

        def quitar_foto(ruta):
            if ruta in fotos_temp:
                fotos_temp.remove(ruta)
            refrescar_preview()

        async def agregar_foto(e):
            loop = asyncio.get_event_loop()
            archivos = await loop.run_in_executor(None, _abrir_dialogo_tkinter_multiple)
            for archivo_origen in archivos:
                nombre_archivo = os.path.basename(archivo_origen)
                destino = os.path.join(PHOTOS_DIR, f"{uuid.uuid4().hex[:8]}_{nombre_archivo}")
                try:
                    shutil.copy(archivo_origen, destino)
                    fotos_temp.append(destino)
                except Exception:
                    pass
            refrescar_preview()

        btn_agregar_foto = ft.ElevatedButton(
            "Agregar fotos", icon=ft.Icons.ADD_A_PHOTO, on_click=agregar_foto
        )

        def cerrar_dialogo(_):
            dialogo.open = False
            page.update()

        def guardar_propiedad(btn_e):
            # Chequeo de permiso otra vez al guardar, por si el estado cambió
            # mientras el diálogo estaba abierto.
            if es_edicion and not puede_gestionar(item):
                error_text.value = "Ya no tenés permiso para editar esta propiedad."
                page.update()
                return

            if not (txt_titulo.value and txt_precio.value and drop_tipo.value):
                error_text.value = "Completá título, precio y tipo antes de publicar."
                page.update()
                return

            if not txt_contacto.value:
                error_text.value = "Agregá un teléfono de contacto para que te puedan escribir."
                page.update()
                return

            try:
                precio = float(txt_precio.value.replace(",", "."))
            except ValueError:
                error_text.value = "El precio debe ser un número válido."
                page.update()
                return

            datos = {
                "titulo": txt_titulo.value,
                "precio": precio,
                "tipo": drop_tipo.value,
                "descripcion": txt_desc.value or "",
                "direccion": txt_direccion.value or "",
                "fotos": list(fotos_temp),
                "contacto": txt_contacto.value or "",
                "email": txt_email.value or "",
            }

            if es_edicion:
                item.update(datos)
            else:
                datos["id"] = str(uuid.uuid4())
                datos["favorito"] = False
                datos["propietario_id"] = state["current_user"]["id"]
                datos["propietario_nombre"] = state["current_user"]["username"]
                properties.append(datos)

            save_properties(properties)
            dialogo.open = False
            page.update()
            render()

        refrescar_preview()

        dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                "Editar propiedad" if es_edicion else "Nueva propiedad",
                weight=ft.FontWeight.BOLD,
                color=INK,
            ),
            content=ft.Column(
                tight=True,
                spacing=12,
                controls=[
                    drop_tipo,
                    txt_titulo,
                    txt_precio,
                    txt_desc,
                    txt_direccion,
                    txt_contacto,
                    txt_email,
                    btn_agregar_foto,
                    fotos_preview_row,
                    error_text,
                ],
                scroll=ft.ScrollMode.AUTO,
                height=480,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=cerrar_dialogo),
                ft.ElevatedButton(
                    "Guardar cambios" if es_edicion else "Publicar",
                    bgcolor=ACTION_BG,
                    color=ACTION_TEXT,
                    on_click=guardar_propiedad,
                ),
            ],
        )

        page.overlay.append(dialogo)
        page.dialog = dialogo
        dialogo.open = True
        page.update()

    # ------------------------------------------------------------------
    # Buscador, orden y rango de precio
    # ------------------------------------------------------------------
    def al_cambiar_busqueda(e):
        state["search_text"] = e.control.value
        render()

    def al_cambiar_orden(e):
        state["sort_value"] = e.control.value
        render()

    def al_cambiar_precio_min(e):
        state["precio_min"] = e.control.value
        render()

    def al_cambiar_precio_max(e):
        state["precio_max"] = e.control.value
        render()

    buscador = ft.TextField(
        hint_text="🔍 Buscar propiedades...",
        expand=True,
        bgcolor=SURFACE,
        border_color=PAPER_2,
        content_padding=12,
    )
    buscador.on_change = al_cambiar_busqueda

    orden_dropdown = ft.Dropdown(
        width=220,
        value=state["sort_value"],
        options=[
            ft.DropdownOption("Más recientes"),
            ft.DropdownOption("Precio: menor a mayor"),
            ft.DropdownOption("Precio: mayor a menor"),
        ],
        border_color=PAPER_2,
        bgcolor=SURFACE,
    )
    orden_dropdown.on_change = al_cambiar_orden

    txt_precio_min = ft.TextField(
        label="Precio mín.",
        width=150,
        keyboard_type=ft.KeyboardType.NUMBER,
        bgcolor=SURFACE,
        border_color=PAPER_2,
        content_padding=12,
    )
    txt_precio_min.on_change = al_cambiar_precio_min

    txt_precio_max = ft.TextField(
        label="Precio máx.",
        width=150,
        keyboard_type=ft.KeyboardType.NUMBER,
        bgcolor=SURFACE,
        border_color=PAPER_2,
        content_padding=12,
    )
    txt_precio_max.on_change = al_cambiar_precio_max

    # ------------------------------------------------------------------
    # Chips de filtro por tipo
    # ------------------------------------------------------------------
    chip_buttons = {}
    chips_row = ft.Row(spacing=6)

    def al_seleccionar_chip(e, tipo):
        state["active_type"] = tipo
        for k, btn in chip_buttons.items():
            btn.bgcolor = VERDIGRIS if k == tipo else SURFACE
            btn.content.color = WHITE if k == tipo else INK_SOFT
        render()

    for label, val in [
        ("Todos", "todos"),
        ("Departamento", "Departamento"),
        ("Casa", "Casa"),
        ("Local", "Local"),
    ]:
        btn = ft.Container(
            content=ft.Text(
                label,
                size=12,
                weight=ft.FontWeight.W_500,
                color=WHITE if val == state["active_type"] else INK_SOFT,
            ),
            padding=ft.Padding.symmetric(horizontal=14, vertical=8),
            border_radius=20,
            bgcolor=VERDIGRIS if val == state["active_type"] else SURFACE,
            border=ft.Border.all(1, PAPER_2),
            on_click=lambda e, v=val: al_seleccionar_chip(e, v),
        )
        chip_buttons[val] = btn
        chips_row.controls.append(btn)

    # ------------------------------------------------------------------
    # Tema claro / oscuro
    # ------------------------------------------------------------------
    def theme_toggle_button():
        """Crea un botón de alternancia de tema fresco, reflejando el modo
        actual. Se usa tanto en el header de la app como en la pantalla de
        login, ya que ambas vistas se reconstruyen por completo al togglear."""
        return ft.IconButton(
            icon=ft.Icons.DARK_MODE if state["theme"] == "light" else ft.Icons.LIGHT_MODE,
            icon_color=INK_SOFT,
            tooltip="Modo oscuro" if state["theme"] == "light" else "Modo claro",
            on_click=toggle_theme,
        )

    def set_theme(mode):
        global INK, INK_SOFT, PAPER, PAPER_2, SURFACE

        palette = DARK_PALETTE if mode == "dark" else LIGHT_PALETTE
        INK = palette["INK"]
        INK_SOFT = palette["INK_SOFT"]
        PAPER = palette["PAPER"]
        PAPER_2 = palette["PAPER_2"]
        SURFACE = palette["SURFACE"]

        state["theme"] = mode
        page.theme_mode = ft.ThemeMode.DARK if mode == "dark" else ft.ThemeMode.LIGHT
        page.bgcolor = PAPER

        # Controles persistentes que no se recrean solos (buscador, filtros,
        # chips): hay que actualizarles el color a mano.
        buscador.bgcolor = SURFACE
        buscador.border_color = PAPER_2
        orden_dropdown.bgcolor = SURFACE
        orden_dropdown.border_color = PAPER_2
        txt_precio_min.bgcolor = SURFACE
        txt_precio_min.border_color = PAPER_2
        txt_precio_max.bgcolor = SURFACE
        txt_precio_max.border_color = PAPER_2
        btn_favoritos_filter.icon_color = BRASS if state["solo_favoritos"] else INK_SOFT

        for val, btn in chip_buttons.items():
            seleccionado = val == state["active_type"]
            btn.bgcolor = VERDIGRIS if seleccionado else SURFACE
            btn.border = ft.Border.all(1, PAPER_2)
            btn.content.color = WHITE if seleccionado else INK_SOFT

        # El header y la pantalla de login se reconstruyen por completo en
        # cada llamada, así que alcanza con volver a mostrarlos.
        if state["current_user"]:
            build_app_view()
        else:
            mostrar_login()

    def toggle_theme(e):
        set_theme("dark" if state["theme"] == "light" else "light")

    # ------------------------------------------------------------------
    # Sesión: login / registro / logout
    # ------------------------------------------------------------------
    def cerrar_sesion(e):
        state["current_user"] = None
        mostrar_login()

    def build_header():
        user = state["current_user"]
        return ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.Icon(ft.Icons.KEY, color=VERDIGRIS, size=28),
                        ft.Text("Llave", size=24, color=INK, weight=ft.FontWeight.BOLD),
                        ft.Text(".", size=24, color=VERDIGRIS, weight=ft.FontWeight.BOLD),
                    ],
                ),
                ft.Row(
                    spacing=10,
                    controls=[
                        ft.Row(
                            spacing=4,
                            controls=[
                                ft.Icon(ft.Icons.PERSON, color=INK_SOFT, size=16),
                                ft.Text(
                                    user["username"] + (" (admin)" if user.get("es_admin") else ""),
                                    size=13,
                                    color=INK_SOFT,
                                ),
                            ],
                        ),
                        theme_toggle_button(),
                        ft.ElevatedButton(
                            "＋  Publicar propiedad",
                            bgcolor=ACTION_BG,
                            color=ACTION_TEXT,
                            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=6)),
                            on_click=lambda e: open_property_dialog(None),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.LOGOUT,
                            icon_color=INK_SOFT,
                            tooltip="Cerrar sesión",
                            on_click=cerrar_sesion,
                        ),
                    ],
                ),
            ],
        )

    def build_app_view():
        page.controls.clear()
        page.add(
            build_header(),
            ft.Divider(height=1, color=PAPER_2),
            ft.Row(controls=[buscador, orden_dropdown], spacing=12),
            ft.Row(
                controls=[txt_precio_min, txt_precio_max, btn_favoritos_filter],
                spacing=12,
            ),
            chips_row,
            result_label,
            galeria_grid,
        )
        render()

    def mostrar_login():
        page.controls.clear()

        txt_user = ft.TextField(
            label="Usuario", width=300, border_color=INK_SOFT, autofocus=True
        )
        txt_pass = ft.TextField(
            label="Contraseña",
            width=300,
            password=True,
            can_reveal_password=True,
            border_color=INK_SOFT,
        )
        error_login = ft.Text("", size=12, color="#C0392B")

        def validar_datos_basicos():
            if not txt_user.value or not txt_user.value.strip():
                error_login.value = "Ingresá un usuario."
                return False
            if not txt_pass.value:
                error_login.value = "Ingresá una contraseña."
                return False
            return True

        def hacer_login(e):
            if not validar_datos_basicos():
                page.update()
                return
            username = txt_user.value.strip()
            user = next(
                (u for u in users if u["username"].lower() == username.lower()), None
            )
            if not user or not verify_password(
                txt_pass.value, user["salt"], user["password_hash"]
            ):
                error_login.value = "Usuario o contraseña incorrectos."
                page.update()
                return
            state["current_user"] = {
                "id": user["id"],
                "username": user["username"],
                "es_admin": user.get("es_admin", False),
            }
            build_app_view()

        def hacer_registro(e):
            if not validar_datos_basicos():
                page.update()
                return
            username = txt_user.value.strip()
            password = txt_pass.value
            if len(password) < 6:
                error_login.value = "La contraseña debe tener al menos 6 caracteres."
                page.update()
                return
            if any(u["username"].lower() == username.lower() for u in users):
                error_login.value = "Ese usuario ya existe. Iniciá sesión."
                page.update()
                return

            salt = secrets.token_hex(16)
            nuevo_usuario = {
                "id": str(uuid.uuid4()),
                "username": username,
                "salt": salt,
                "password_hash": hash_password(password, salt),
                # El primer usuario registrado queda como admin, para poder
                # gestionar propiedades viejas sin dueño asignado.
                "es_admin": len(users) == 0,
            }
            users.append(nuevo_usuario)
            save_users(users)

            state["current_user"] = {
                "id": nuevo_usuario["id"],
                "username": nuevo_usuario["username"],
                "es_admin": nuevo_usuario["es_admin"],
            }
            build_app_view()

        page.add(
            ft.Column(
                expand=True,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.END,
                        controls=[theme_toggle_button()],
                    ),
                    ft.Container(
                        expand=True,
                        alignment=_center_alignment(),
                        content=ft.Column(
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=12,
                            controls=[
                                ft.Icon(ft.Icons.KEY, color=VERDIGRIS, size=48),
                                ft.Row(
                                    controls=[
                                        ft.Text(
                                            "Llave", size=32, color=INK, weight=ft.FontWeight.BOLD
                                        ),
                                        ft.Text(
                                            ".",
                                            size=32,
                                            color=VERDIGRIS,
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                    ]
                                ),
                                ft.Text(
                                    "Ingresá para publicar y gestionar tus propiedades",
                                    size=13,
                                    color=INK_SOFT,
                                ),
                                ft.Container(height=10),
                                txt_user,
                                txt_pass,
                                error_login,
                                ft.ElevatedButton(
                                    "Ingresar",
                                    width=300,
                                    bgcolor=ACTION_BG,
                                    color=ACTION_TEXT,
                                    on_click=hacer_login,
                                ),
                                ft.TextButton(
                                    "¿No tenés cuenta? Registrate",
                                    on_click=hacer_registro,
                                ),
                            ],
                        ),
                    ),
                ],
            )
        )
        page.update()

    # ------------------------------------------------------------------
    # Punto de entrada
    # ------------------------------------------------------------------
    mostrar_login()


ft.app(target=main)
