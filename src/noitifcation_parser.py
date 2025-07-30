import base64
import os
from pprint import pprint

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib  # type: ignore  # noqa: E402, F821


class NotificationParser:
    def __init__(
        self,
        id: int,
        app_name: str,
        replaces_id: int,
        app_icon: str,
        summary: str,
        body: str,
        actions: list[str],
        hints: dict[str, str],
        replaceable: bool = False,
        expire_timeout: int = 5000,
    ):
        self.id = id
        self.app_name = app_name
        self.replaces_id = replaces_id
        self.app_icon = app_icon
        self.title = summary
        self.subtitle: str | None = None
        self.body = body
        self.actions = actions
        self.hints = hints
        self.expire_timeout = expire_timeout
        self.replaceable = replaceable

        # pprint(
        #     {
        #         "app_name": app_name,
        #         "replaces_id": replaces_id,
        #         "app_icon": app_icon,
        #         "title": summary,
        #         "body": body,
        #         "actions": actions,
        #         # "hints": hints,
        #         "expire_timeout": expire_timeout,
        #     },
        #     compact=True,
        #     depth=1,
        # )

        self.parse()

    def parse(self):
        self.parse_image()
        self.parse_content()

    def parse_content(self):
        if self.app_name == "elecwhat":
            self.title = self.title[len(self.app_name) + 3 :]

            if len(self.body.split("\u200e")) > 1:
                self.subtitle = self.body.split(": ")[0]
                self.body = self.body.split("\u200e:")[1]

        if self.app_name in self.title:
            self.title = self.title[len(self.app_name) + 3 :]

    def has_image_data(self) -> str:
        """Check if the notification has image data."""
        if "image-data" in self.hints:
            return "image-data"
        if "icon_data" in self.hints:
            return "icon_data"
        return ""

    def parse_image(self):
        """Parse the image data from the hints."""
        print(self.hints.keys())
        if key := self.has_image_data():
            wrapped_data = self.hints.get(key)
            image = self.unwrap_variant(wrapped_data)

            self.img = self.image_data_to_base64_png(image)
            return

        self.img = self.search_app_image()

    def search_app_image(self):
        """Search for the application icon image using KISS principle."""
        # Simple approach: check common locations where app icons are stored
        icon_name = self.app_icon or self.app_name or ""
        if not icon_name:
            return ""

        # Clean the icon name
        icon_name = icon_name.lower().strip()

        # Handle specific app name mappings where app_name differs from icon name
        app_mappings = {
            # VS Code reports as "Code" but icon is "visual-studio-code"
            "code": "visual-studio-code",
        }

        # Check if we need to use a mapped name
        mapped_name = app_mappings.get(icon_name)
        if mapped_name:
            icon_name = mapped_name

        # Common icon directories (most apps store icons here)
        search_paths = [
            "/usr/share/pixmaps",  # Direct pixmaps (like Alacritty)
            "/usr/share/icons/hicolor/48x48/apps",  # Most common size
            "/usr/share/icons/hicolor/64x64/apps",
            "/usr/share/icons/hicolor/128x128/apps",
            "/usr/share/icons/hicolor/256x256/apps",  # Discord is here
            "/usr/local/share/pixmaps",
        ]

        extensions = [".png", ".svg", ".xpm", ".ico"]

        # Try variations of the icon name (including original case and common suffixes)
        name_variations = [
            icon_name,  # lowercase version
            icon_name.replace(" ", "-"),
            icon_name.replace(" ", "_"),
            self.app_name or self.app_icon or "",  # original case
            (self.app_name or self.app_icon or "").replace(" ", "-"),
            (self.app_name or self.app_icon or "").replace(" ", "_"),
            # Common app suffixes
            f"{icon_name}-desktop",  # brave -> brave-desktop
            f"{icon_name}-browser",  # might be used by browsers
            f"{icon_name}browser",  # concatenated version
            f"{(self.app_name or self.app_icon or '').lower()}-desktop",
        ]

        # Remove empty strings and duplicates
        name_variations = list(set(v for v in name_variations if v))

        for search_path in search_paths:
            if not os.path.exists(search_path):
                continue

            for name in name_variations:
                for ext in extensions:
                    icon_path = os.path.join(search_path, f"{name}{ext}")
                    if os.path.isfile(icon_path):
                        return self._convert_icon_to_base64(icon_path)

        # If nothing found, return empty
        return ""

    def _convert_icon_to_base64(self, icon_path):
        """Convert icon file to base64 PNG."""
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(icon_path)

            # Resize to 48x48 max for consistency
            if pixbuf.get_width() > 48 or pixbuf.get_height() > 48:
                pixbuf = pixbuf.scale_simple(
                    48, 48, GdkPixbuf.InterpType.BILINEAR
                )

            success, buffer = pixbuf.save_to_bufferv("png", [], [])
            if success:
                return base64.b64encode(buffer).decode("utf-8")
        except Exception as e:
            print(f"Error loading icon {icon_path}: {e}")

        return ""

    def unwrap_variant(self, value):
        """Recursively unwrap dbus_next Variants to Python types."""
        from dbus_next import Variant

        if isinstance(value, Variant):
            return self.unwrap_variant(value.value)
        elif isinstance(value, dict):
            return {k: self.unwrap_variant(v) for k, v in value.items()}
        elif isinstance(value, (list, tuple)):
            return type(value)(self.unwrap_variant(v) for v in value)
        return value

    def image_data_to_base64_png(self, image_data):
        (
            width,
            height,
            rowstride,
            has_alpha,
            bits_per_sample,
            channels,
            data,
        ) = image_data

        pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
            GLib.Bytes(data),
            GdkPixbuf.Colorspace.RGB,
            has_alpha,
            bits_per_sample,
            width,
            height,
            rowstride,
        )

        success, buffer = pixbuf.save_to_bufferv("png", [], [])
        if not success:
            return None
        return base64.b64encode(buffer).decode("utf-8")
