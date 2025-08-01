import json
import os

from const import NOTIFICATION_PADDING

os.environ["GDK_BACKEND"] = "wayland"

import gi

from noitifcation_parser import NotificationParser

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import (  # noqa: E402
    Gdk,  # type: ignore  # noqa: E402
    GLib,  # type: ignore  # noqa: E402
    Gtk,  # type: ignore  # noqa: E402
    GtkLayerShell,  # type: ignore  # noqa: E402
    WebKit2,  # type: ignore  # noqa: E402
)


def create_notification_window(
    notification: NotificationParser,
    action_callback=None,
) -> Gtk.Window:
    """
    Create a GTK notification window with layer shell support for workspace persistence.

    Args:
        notification: NotificationParser containing notification data
        action_callback: Callback function for handling actions

    Returns:
        Gtk.Window: Configured notification window
    """
    window = Gtk.Window()
    window.notification = notification
    window.action_callback = action_callback

    GtkLayerShell.init_for_window(window)

    _set_window_conf(window)

    webview = _create_webview(notification, window)

    window.add(webview)

    window._width = 320
    window._height = 100
    window._webview = webview

    webview.connect(
        "load-changed",
        lambda _, event: _on_content_loaded(window, webview, event),
    )

    _setup_layer_shell_properties(window)

    window.show_all()
    window.present()

    return window


def _setup_layer_shell_properties(
    window: Gtk.Window, screen_pos: int = NOTIFICATION_PADDING
) -> None:
    """Configure layer shell properties after initialization."""
    try:
        GtkLayerShell.set_layer(window, GtkLayerShell.Layer.OVERLAY)

        GtkLayerShell.set_namespace(window, "notifications")

        GtkLayerShell.set_anchor(window, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(window, GtkLayerShell.Edge.RIGHT, True)

        window.screen_pos = screen_pos
        GtkLayerShell.set_margin(window, GtkLayerShell.Edge.TOP, screen_pos)
        GtkLayerShell.set_margin(
            window, GtkLayerShell.Edge.RIGHT, NOTIFICATION_PADDING
        )

        GtkLayerShell.auto_exclusive_zone_enable(window)

    except Exception as e:
        print(f"✗ Layer shell property setup failed: {e}")
        import traceback

        traceback.print_exc()


def _set_window_conf(window: Gtk.Window) -> None:
    """Configure window properties."""
    window.set_role("my-notification")
    window.set_title("MyNotificationWindow")

    window.set_size_request(320, 68)

    window.set_decorated(False)
    window.set_resizable(True)
    window.set_keep_above(True)
    window.set_app_paintable(True)

    window.set_accept_focus(False)
    window.set_focus_on_map(False)
    window.set_can_focus(False)

    screen = window.get_screen()
    visual = screen.get_rgba_visual()
    if visual:
        window.set_visual(visual)


def _create_webview(
    notification: NotificationParser, window: Gtk.Window
) -> WebKit2.WebView:
    """Create and configure the WebKit webview."""
    webview = WebKit2.WebView()
    webview.set_name("notification-webview")
    webview.get_settings().set_enable_javascript(True)
    webview.get_settings().set_javascript_can_open_windows_automatically(False)
    webview.get_settings().set_enable_back_forward_navigation_gestures(False)
    webview.get_settings().set_enable_developer_extras(True)

    webview.set_size_request(-1, -1)
    webview.set_editable(False)

    webview.connect("context-menu", lambda *args: True)
    webview.connect("decide-policy", _on_decide_policy)

    # Set transparent background
    try:
        rgba = Gdk.RGBA()
        rgba.parse("rgba(0, 0, 0, 0)")
        webview.set_background_color(rgba)
    except Exception:
        pass

    # Prepare actions data for JavaScript with proper escaping
    actions_data = _prepare_actions_data(notification.actions)
    actions_json = json.dumps(actions_data) if actions_data else "[]"

    # Helper function to escape strings for HTML/JS
    def escape_for_html(text):
        if not text:
            return ""
        return (
            text.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        )

    # Load notification content with proper escaping
    html = (
        open("templates/notification.html", "r", encoding="utf-8")
        .read()
        .replace("{title}", escape_for_html(notification.title))
        .replace("{body}", escape_for_html(notification.body))
        .replace("{subtitle}", escape_for_html(notification.subtitle or ""))
        .replace("{img}", notification.img or "")
        .replace("{app_name}", escape_for_html(notification.app_name or ""))
        .replace("{actions}", actions_json)
        .replace("{notification_id}", str(notification.id))
    )
    webview.load_html(html, "file:///")

    # Set up JavaScript message handling for actions
    user_content_manager = webview.get_user_content_manager()
    user_content_manager.connect(
        "script-message-received::action",
        lambda _, message: _handle_action_message(window, message),
    )
    user_content_manager.register_script_message_handler("action")

    # Show inspector for debugging (comment out for production)
    # inspector = webview.get_inspector()
    # inspector.show()

    return webview


def _prepare_actions_data(actions):
    """Convert actions array to structured data for JavaScript."""
    if not actions:
        return []

    action_buttons = []
    # Actions come in pairs: action_key, action_label
    for i in range(0, len(actions), 2):
        if i + 1 < len(actions):
            action_key = actions[i]
            action_label = actions[i + 1]
            action_buttons.append({"key": action_key, "label": action_label})

    return action_buttons


def _handle_action_message(window: Gtk.Window, message):
    """Handle action messages from JavaScript."""
    try:
        # Get the message body (action key)
        js_value = message.get_js_value()
        action_key = (
            js_value.to_string()
            if hasattr(js_value, "to_string")
            else str(js_value)
        )

        # Call the action callback if available
        if window.action_callback and hasattr(window, "notification"):
            window.action_callback(window.notification.id, action_key)

    except Exception as e:
        print(f"Error handling action message: {e}")


def _on_content_loaded(
    window: Gtk.Window, webview: WebKit2.WebView, load_event
) -> None:
    """Auto-resize window when WebView content is fully loaded."""
    if load_event == WebKit2.LoadEvent.FINISHED:
        GLib.timeout_add(100, lambda: _auto_resize_window(window))


def _auto_resize_window(window: Gtk.Window) -> bool:
    """Resize window to fit WebView content using JavaScript to get DOM size."""
    webview = window._webview

    # JavaScript to get both width and height of the actual rendered content
    js_code = """
    (function() {
        // Force layout to ensure measurements are accurate
        document.body.offsetHeight;
        document.body.offsetWidth;

        // Get the actual bounding box of the body element
        var bodyRect = document.body.getBoundingClientRect();

        // Return both dimensions as JSON string
        return JSON.stringify({
            width: Math.ceil(bodyRect.width),
            height: Math.ceil(bodyRect.height)
        });
    })();
    """

    webview.run_javascript(
        js_code,
        None,
        lambda _, result, data: _on_js_dimensions_result(
            window, webview, result, data
        ),
        None,
    )
    return False  # Don't repeat


def _on_js_dimensions_result(
    window: Gtk.Window, webview: WebKit2.WebView, result, user_data
) -> None:
    """Handle the JavaScript result with actual content dimensions."""
    try:
        js_result = webview.run_javascript_finish(result)

        if hasattr(js_result, "get_js_value"):
            js_value = js_result.get_js_value()
            if hasattr(js_value, "to_string"):
                dimensions_str = js_value.to_string()
            elif hasattr(js_value, "get_string"):
                dimensions_str = js_value.get_string()
            else:
                dimensions_str = str(js_value)
        else:
            dimensions_str = str(js_result)

        dimensions = json.loads(dimensions_str.strip())
        content_width = dimensions["width"]
        content_height = dimensions["height"]

        new_width = content_width
        new_height = content_height

        if new_width < 200:
            new_width = 200
        if new_height < 50:
            new_height = 50

        window._width = new_width + 2
        window._height = new_height + 2

        # print(window._width, window._height)

        # window.resize(window._width, window._height)
        window.set_size_request(window._width, window._height)
        webview.set_size_request(window._width, window._height)

        window.show_all()

    except Exception as e:
        print(f"Error getting content dimensions: {e}")
        import traceback

        traceback.print_exc()
        # Fallback to reasonable defaults
        fallback_width = 320
        fallback_height = 80
        window._width = fallback_width
        window._height = fallback_height
        window.resize(fallback_width, fallback_height)
        webview.set_size_request(fallback_width, fallback_height)


def _on_decide_policy(
    webview: WebKit2.WebView, decision, decision_type
) -> None:
    """Handle WebView navigation policy decisions."""
    if decision_type == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
        navigation_action = decision.get_navigation_action()
        request = navigation_action.get_request()
        uri = request.get_uri()

        if uri in ("file:///", "") or uri.startswith("data:"):
            decision.use()
        else:
            decision.ignore()
        return
    decision.use()
