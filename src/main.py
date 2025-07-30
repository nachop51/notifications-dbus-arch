import asyncio
import os

from const import NOTIFICATION_PADDING, SCREEN_HEIGHT_THRESHOLD

# Force Wayland backend BEFORE importing any GTK-related modules
os.environ["GDK_BACKEND"] = "wayland"

import gi
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method

from noitifcation_parser import NotificationParser
from notification_window import create_notification_window

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import (  #  # noqa: E402
    GLib,  # type: ignore  # noqa: E402, F821
    Gtk,  # type: ignore  # noqa: E402, F821
    GtkLayerShell,  # type: ignore  # noqa: E402, F821
)


class Notifications(ServiceInterface):
    _counter = 0
    _nots = {}

    def __init__(self, app):
        super().__init__("org.freedesktop.Notifications")
        self.app = app

    @method()
    def GetServerInformation(self) -> "ssss":  # type: ignore # noqa: F821
        return [
            "Nachotifications",  # name
            "ndev51",  # vendor
            "1.0.0",  # version
            "1.0",  # spec_version
        ]

    @method()
    def GetCapabilities(self) -> "as":  # type: ignore  # noqa: F722, F821
        return [
            "body",
            "actions",
            "action-icons",
            "body-hyperlinks",
            "body-images",
            "body-markup",
            "icon-multi",
            "icon-static",
            "persistence",
        ]

    @method()
    def Notify(
        self,
        app_name: "s",  # type: ignore # noqa: F821
        replaces_id: "u",  # type: ignore # noqa: F821
        app_icon: "s",  # type: ignore # noqa: F821
        summary: "s",  # type: ignore # noqa: F821
        body: "s",  # type: ignore # noqa: F821
        actions: "as",  # type: ignore  # noqa: F722, F821
        hints: "a{sv}",  # type: ignore  # noqa: F722, F821
        expire_timeout: "i",  # type: ignore # noqa: F821
    ) -> "u":  # type: ignore # noqa: F821
        """Send a notification"""
        self._counter += 1

        notification = NotificationParser(
            self._counter,
            app_name,
            replaces_id,
            app_icon,
            summary,
            body,
            actions,
            hints,
        )

        win = create_notification_window(notification)

        for notf in list(self._nots.values()):
            notf.screen_pos = (
                notf.screen_pos + notf._height + NOTIFICATION_PADDING
            )
            if notf.screen_pos < SCREEN_HEIGHT_THRESHOLD:
                GtkLayerShell.set_margin(
                    notf,
                    GtkLayerShell.Edge.TOP,
                    notf.screen_pos,
                )
            else:
                self._close_window(notf, notf.notification)

        win.show_all()

        self._nots[self._counter] = win

        GLib.timeout_add_seconds(
            notification.expire_timeout / 1000,
            lambda: self._close_window(win, notification),
        )

        return self._counter

    @method()
    def CloseNotification(self, id: "u", by_program: "b"):  # type: ignore # noqa: F821
        print(f"{id = }")
        notf_to_delete = self._nots.get(id)
        if notf_to_delete and by_program is True:
            del self._nots[id]

    def _close_window(
        self, window: Gtk.Window, notification: NotificationParser
    ) -> bool:
        """Close and destroy the window."""
        window.destroy()

        self.CloseNotification(notification.id, by_program=True)

        return False  # Don't repeat the timeout


async def setup_dbus(app):
    bus = await MessageBus().connect()
    notifications = Notifications(app)
    bus.export("/org/freedesktop/Notifications", notifications)
    await bus.request_name("org.freedesktop.Notifications")


def main():
    app = Gtk.Application(application_id="com.example.MyNotification")

    def on_activate(app):
        app.hold()  # <-- Prevents immediate exit

    app.connect("activate", on_activate)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def iterate_asyncio():
        loop.stop()
        loop.run_forever()
        return True

    GLib.timeout_add(10, iterate_asyncio)

    loop.create_task(setup_dbus(app))

    app.run(None)


if __name__ == "__main__":
    main()
