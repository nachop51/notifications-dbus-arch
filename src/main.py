import asyncio
import json
import os
import re
import subprocess

from const import NOTIFICATION_PADDING, SCREEN_HEIGHT_THRESHOLD

# Force Wayland backend BEFORE importing any GTK-related modules
os.environ["GDK_BACKEND"] = "wayland"

import gi
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method, signal

from noitifcation_parser import NotificationParser
from notification_window import create_notification_window

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import (  #  # noqa: E402
    GLib,  # type: ignore  # noqa: E402, F821
    Gtk,  # type: ignore  # noqa: E402, F821
    GtkLayerShell,  # type: ignore  # noqa: E402, F821
)


class ClosedReason:
    expired = 1
    dismissed = 2
    method = 3


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
            "1.0.1",  # version
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

    @signal()
    def ActionInvoked(self, id: "u", action_key: "s") -> "us":  # type: ignore # noqa: F821
        """Signal emitted when an action is invoked"""
        return [id, action_key]

    @signal()
    def NotificationClosed(self, id: "u", reason: "u") -> "uu":  # type: ignore # noqa: F821
        """Signal emitted when notification is closed"""
        return [id, reason]

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

        win = create_notification_window(notification, self._on_action_invoked)

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
        notf_to_delete = self._nots.get(id)
        if notf_to_delete and by_program is True:
            del self._nots[id]

    def _on_action_invoked(self, notification_id: int, action_key: str):
        """Handle action invoked from JavaScript"""
        print(
            f"Action invoked: {action_key} for notification {notification_id}"
        )

        window = self._nots.get(notification_id)
        if not window or not hasattr(window, "notification"):
            return

        notification = window.notification

        self._handle_notification_action(notification, action_key)

        self.ActionInvoked(notification_id, action_key)

        # Close notification after action is invoked
        self._close_window_by_id(
            notification_id, reason=ClosedReason.dismissed
        )

    def _handle_notification_action(
        self, notification: NotificationParser, action_key: str
    ):
        """Handle specific actions based on app and action type"""
        app_name = notification.app_name.lower()

        try:
            if app_name in [
                "discord",
                "element",
                "telegram",
                "whatsapp",
                "signal",
            ]:
                self._handle_chat_app_action(notification, action_key)
            elif app_name in ["thunderbird", "evolution", "geary"]:
                self._handle_email_app_action(notification, action_key)
            elif app_name in ["code", "visual studio code", "vscode"]:
                self._handle_code_app_action(notification, action_key)
            else:
                # Generic app focusing
                self._focus_application_window(app_name)

        except Exception as e:
            print(f"Error handling action for {app_name}: {e}")

    def _handle_chat_app_action(
        self, notification: NotificationParser, action_key: str
    ):
        """Handle chat application actions"""
        app_name = notification.app_name.lower()

        # Focus the application window first
        self._focus_application_window(app_name)

        # Try to extract chat/channel info from notification content
        if action_key in ["reply", "open", "show"]:
            chat_info = self._extract_chat_info(notification)

            if app_name == "discord":
                self._handle_discord_action(chat_info, action_key)
            elif app_name in ["telegram", "whatsapp"]:
                self._handle_messaging_app_action(
                    app_name, chat_info, action_key
                )

    def _handle_email_app_action(
        self, notification: NotificationParser, action_key: str
    ):
        """Handle email application actions"""
        app_name = notification.app_name.lower()
        self._focus_application_window(app_name)

    def _handle_code_app_action(
        self, notification: NotificationParser, action_key: str
    ):
        """Handle VS Code/editor actions"""
        self._focus_application_window("code")

        # VS Code notifications often contain file paths or build results
        if action_key == "open" and "error" in notification.body.lower():
            # Try to parse file path from error message
            file_match = re.search(r"([/\w.-]+\.\w+)", notification.body)
            if file_match:
                file_path = file_match.group(1)
                subprocess.run(["code", "--goto", file_path], check=False)

    def _extract_chat_info(self, notification: NotificationParser):
        """Extract chat/channel information from notification"""
        chat_info = {
            "title": notification.title,
            "subtitle": notification.subtitle,
            "body": notification.body,
            "app_name": notification.app_name,
        }

        # Try to extract username or channel name
        if notification.subtitle:
            chat_info["chat_name"] = notification.subtitle.strip()
        elif ":" in notification.title:
            chat_info["chat_name"] = notification.title.split(":")[0].strip()

        return chat_info

    def _handle_discord_action(self, chat_info: dict, action_key: str):
        """Handle Discord-specific actions"""
        if action_key == "reply":
            chat_name = chat_info.get("chat_name", "")
            print(f"Opening Discord chat: {chat_name}")

            # Use Discord's quick switcher (Ctrl+K)
            self._send_hyprland_keys(["CTRL", "K"])

    def _handle_messaging_app_action(
        self, app_name: str, chat_info: dict, action_key: str
    ):
        """Handle messaging app actions"""
        chat_name = chat_info.get("chat_name", "")
        print(f"Opening {app_name} chat: {chat_name}")

        if action_key == "reply":
            # Many messaging apps use Ctrl+F to search/find chats
            self._send_hyprland_keys(["CTRL", "F"])

    def _focus_application_window(self, app_name: str):
        """Focus the application window using Hyprland commands"""
        try:
            # Get list of all windows from Hyprland
            result = subprocess.run(
                ["hyprctl", "clients", "-j"],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode == 0:
                clients = json.loads(result.stdout)

                # Find window by class or title
                target_window = None
                for client in clients:
                    window_class = client.get("class", "").lower()
                    window_title = client.get("title", "").lower()

                    # Match app name to window class or title
                    if (
                        app_name in window_class
                        or app_name in window_title
                        or self._match_app_to_class(app_name, window_class)
                    ):
                        target_window = client
                        break

                if target_window:
                    # Focus the window using Hyprland
                    window_address = target_window.get("address", "")
                    if window_address:
                        subprocess.run(
                            [
                                "hyprctl",
                                "dispatch",
                                "focuswindow",
                                f"address:{window_address}",
                            ],
                            check=False,
                        )
                        return True

                    # Alternative: focus by class
                    window_class = target_window.get("class", "")
                    if window_class:
                        subprocess.run(
                            [
                                "hyprctl",
                                "dispatch",
                                "focuswindow",
                                f"class:^{window_class}$",
                            ],
                            check=False,
                        )
                        return True

        except (
            subprocess.CalledProcessError,
            json.JSONDecodeError,
            FileNotFoundError,
        ) as e:
            print(f"Error focusing window with Hyprland: {e}")

        # Fallback: try to launch the application
        try:
            subprocess.run(
                [app_name],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            print(f"Could not focus or launch {app_name}")

        return False

    def _match_app_to_class(self, app_name: str, window_class: str) -> bool:
        """Match application name to window class with common mappings"""
        app_mappings = {
            "discord": ["discord", "discordcanary"],
            "telegram": [
                "telegram-desktop",
                "telegramdesktop",
                "org.telegram.desktop",
            ],
            "whatsapp": ["whatsapp-for-linux", "whatsapp", "elecwhat"],
            "signal": ["signal", "org.signal.signal"],
            "code": ["code", "code-oss", "visual-studio-code"],
            "thunderbird": ["thunderbird", "mozilla-thunderbird"],
            "firefox": ["firefox", "firefox-esr"],
            "chrome": ["google-chrome", "chromium", "chromium-browser"],
        }

        possible_classes = app_mappings.get(app_name, [app_name])
        return any(cls in window_class for cls in possible_classes)

    def _send_hyprland_keys(self, keys: list):
        """Send keyboard shortcut using Hyprland dispatcher"""
        try:
            # Small delay to ensure window is focused
            subprocess.run(["sleep", "0.1"], check=False)

            # Send key combination using Hyprland
            key_combination = " ".join(keys)
            subprocess.run(
                [
                    "hyprctl",
                    "dispatch",
                    "sendshortcut",
                    key_combination,
                    "class:^.*$",
                ],
                check=False,
            )

        except FileNotFoundError:
            print("Hyprland not available for keyboard shortcuts")
        except Exception as e:
            print(f"Error sending keys via Hyprland: {e}")

    def _close_window_by_id(
        self, notification_id: int, reason: int = ClosedReason.expired
    ):
        """Close window by notification ID"""
        window = self._nots.get(notification_id)
        if window:
            window.destroy()
            del self._nots[notification_id]
            self.NotificationClosed(notification_id, reason)

    def _close_window(
        self, window: Gtk.Window, notification: NotificationParser
    ) -> bool:
        """Close and destroy the window."""
        window.destroy()

        if notification.id in self._nots:
            del self._nots[notification.id]
            self.NotificationClosed(notification.id, ClosedReason.expired)

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

# TODO: Render images if possible
# for example, when it is a screenshot, display
# the screenshot instead of just a regular message
# For whatsapp/discord or another apps, try to render the image
# when possible
