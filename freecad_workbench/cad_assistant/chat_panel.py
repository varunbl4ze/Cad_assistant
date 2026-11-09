"""
chat_panel.py - the sidebar UI: the chat widget and the code that docks it
into FreeCAD's main window.

Commands you can type in the chat:
    /box <length> <width> <height>   create a box (millimetres)
    /cylinder <radius> <height>      create a cylinder
    /sphere <radius>                 create a sphere
    /list                            list the objects in the active document
    /move <name> <x> <y> <z>         move an object to a position (mm)
    /delete <name>                   delete an object
    /url [address]                   show or change the backend URL
    /help                            list the commands
"""

import html
import math
import queue
import threading

import FreeCADGui

# FreeCAD ships a "PySide" alias that points at whichever Qt binding this
# FreeCAD version uses (PySide2 or PySide6), so the same code runs on both.
from PySide import QtCore, QtGui

try:
    from PySide import QtWidgets
except ImportError:  # very old FreeCAD keeps widgets in QtGui
    QtWidgets = QtGui

from cad_assistant import backend_client, cad_actions

DOCK_NAME = "CADAssistantDock"
PANEL_WIDTH = 360          # width of the sidebar the first time it opens (you can resize it)
CHECK_INTERVAL_MS = 10000  # re-check the backend every 10 s while the panel is visible

# Colours (dark, warm grey, inspired by Claude)
BG = "#262624"
SURFACE = "#30302e"
BORDER = "#444441"
TEXT = "#f0eee6"
MUTED = "#9b9a94"
ACCENT = "#d97757"
GREEN = "#6fbf73"
RED = "#e5786d"

# This stylesheet is set on our panel only, so it cannot restyle the rest of FreeCAD.
STYLE = """
QWidget#CADAssistantPanel { background-color: %(BG)s; }
QLabel { color: %(TEXT)s; }
QLabel#title { font-size: 15px; font-weight: 600; }
QLabel#status { color: %(MUTED)s; font-size: 11px; }
QPushButton {
    background-color: %(SURFACE)s; color: %(TEXT)s;
    border: 1px solid %(BORDER)s; border-radius: 6px; padding: 5px 10px;
}
QPushButton:hover { background-color: #3a3a37; }
QPushButton#send { background-color: %(ACCENT)s; border: none; color: white; font-weight: 600; }
QPushButton#send:hover { background-color: #c8664a; }
QTextBrowser#chat { background-color: %(BG)s; color: %(TEXT)s; border: none; }
QLineEdit {
    background-color: %(SURFACE)s; color: %(TEXT)s;
    border: 1px solid %(BORDER)s; border-radius: 8px; padding: 7px 10px;
}
QLineEdit:focus { border: 1px solid %(ACCENT)s; }
""" % dict(BG=BG, SURFACE=SURFACE, BORDER=BORDER, TEXT=TEXT, MUTED=MUTED, ACCENT=ACCENT)

WELCOME = (
    "Hi, I'm the CAD Assistant. This is an early version and I don't use AI yet.\n"
    "Try: /box 50 20 10   (length width height, in mm)\n"
    "Type /help to see all commands."
)
HELP = (
    "Commands (sizes in mm, all greater than 0):\n"
    "/box <length> <width> <height>\n"
    "/cylinder <radius> <height>\n"
    "/sphere <radius>\n"
    "/list  show the objects in the active document (names, sizes, positions)\n"
    "/move <name> <x> <y> <z>  put an object at a position (mm, can be negative)\n"
    "/delete <name>  delete an object (Ctrl+Z restores it)\n"
    "/url [address]  show or change the backend URL\n"
    "/help  show this list"
)
USAGE_BOX = "Usage: /box <length> <width> <height>\nExample: /box 50 20 10  (mm, all greater than 0)"
USAGE_CYLINDER = "Usage: /cylinder <radius> <height>\nExample: /cylinder 10 30  (mm, both greater than 0)"
USAGE_SPHERE = "Usage: /sphere <radius>\nExample: /sphere 15  (mm, greater than 0)"
USAGE_MOVE = "Usage: /move <name> <x> <y> <z>\nExample: /move Cylinder 100 0 0  (mm, can be negative; see /list for names)"
USAGE_DELETE = "Usage: /delete <name>\nExample: /delete Box  (see /list for names)"
PLACEHOLDER_REPLY = (
    "This is a placeholder reply, since AI responses are not added yet. "
    "Type /help to see the commands that work now."
)


class ChatPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CADAssistantPanel")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)  # lets the stylesheet paint the background
        self.setMinimumWidth(240)
        self.setStyleSheet(STYLE)

        self._connected = None  # None = not checked yet, True = online, False = offline
        self._last_message = ""
        self._checking = False

        # Background threads put their results in this queue; a timer on the
        # UI thread picks them up. (Only the UI thread may touch widgets.)
        self._results = queue.Queue()
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.timeout.connect(self._drain_results)
        self._poll_timer.start(100)  # every 0.1 s; this is very cheap

        self._build_ui()

        # Re-checks the backend now and then, but only while the panel is visible.
        self._check_timer = QtCore.QTimer(self)
        self._check_timer.timeout.connect(self.check_backend)

        self._set_status("checking")
        self._show_welcome()

    # ---------- building the interface ----------

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Top row: title + New Chat button
        top = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("CAD Assistant")
        title.setObjectName("title")
        top.addWidget(title)
        top.addStretch()
        self.new_chat_button = QtWidgets.QPushButton("New Chat")
        self.new_chat_button.clicked.connect(self.new_chat)
        top.addWidget(self.new_chat_button)
        layout.addLayout(top)

        # Connection status
        self.status_label = QtWidgets.QLabel()
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Conversation area
        self.chat = QtWidgets.QTextBrowser()
        self.chat.setObjectName("chat")
        layout.addWidget(self.chat, 1)  # stretch = 1: takes all spare space

        # Input row: text field + Send button
        bottom = QtWidgets.QHBoxLayout()
        self.input = QtWidgets.QLineEdit()
        self.input.setPlaceholderText("Message CAD Assistant...")
        self.input.returnPressed.connect(self.send_message)  # Enter key
        bottom.addWidget(self.input, 1)
        self.send_button = QtWidgets.QPushButton("Send")
        self.send_button.setObjectName("send")
        self.send_button.clicked.connect(self.send_message)
        bottom.addWidget(self.send_button)
        layout.addLayout(bottom)

    # ---------- chat ----------

    def _add_message(self, sender, text, kind="assistant"):
        """Append one message. Text is HTML-escaped so it is always shown literally."""
        safe_text = html.escape(text).replace("\n", "<br>")
        background = SURFACE if kind == "user" else BG
        color = {"error": RED}.get(kind, TEXT)
        self.chat.append(
            '<table width="100%%" cellspacing="0" cellpadding="8"><tr>'
            '<td bgcolor="%s">'
            '<span style="color:%s; font-size:11px;">%s</span><br>'
            '<span style="color:%s;">%s</span>'
            "</td></tr></table>" % (background, MUTED, html.escape(sender), color, safe_text)
        )
        # Scroll after Qt has laid out the new text; scrolling immediately can stop one message short.
        QtCore.QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        bar = self.chat.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _show_welcome(self):
        self._add_message("CAD Assistant", WELCOME)

    def new_chat(self):
        self.chat.clear()
        self._show_welcome()
        self.check_backend()
        self.input.setFocus()

    def send_message(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()

        self._add_message("You", text, "user")

        if text.startswith("/"):
            self._handle_command(text)
            return

        self._add_message("CAD Assistant", PLACEHOLDER_REPLY)
        if self._connected is False:  # only mention the backend if we know it is down
            self._add_message("CAD Assistant", "Backend not connected. " + self._last_message, "error")
        self.check_backend()  # refresh the indicator

    # ---------- commands typed like /box 50 20 10 ----------

    def _handle_command(self, text):
        parts = text.split()
        handlers = {
            "/box": self._cmd_box,
            "/cylinder": self._cmd_cylinder,
            "/sphere": self._cmd_sphere,
            "/list": self._cmd_list,
            "/move": self._cmd_move,
            "/delete": self._cmd_delete,
            "/url": self._cmd_url,
            "/help": self._cmd_help,
        }
        handler = handlers.get(parts[0].lower())
        if handler is None:
            self._add_message(
                "CAD Assistant", "Unknown command: %s\nType /help to see the commands." % parts[0], "error"
            )
            return
        handler(parts[1:])  # pass everything after the command name

    def _cmd_help(self, args):
        self._add_message("CAD Assistant", HELP)

    @staticmethod
    def _positive_numbers(args, count):
        """Return `count` positive, finite numbers from args, or None if they are not valid."""
        if len(args) != count:
            return None
        try:
            values = [float(a) for a in args]
        except ValueError:
            return None
        if not all(math.isfinite(v) and v > 0 for v in values):
            return None
        return values

    def _cmd_box(self, args):
        values = self._positive_numbers(args, 3)
        if values is None:
            self._add_message("CAD Assistant", USAGE_BOX, "error")
            return
        length, width, height = values
        self._run_backend_command("create_box", {"length": length, "width": width, "height": height})

    def _cmd_cylinder(self, args):
        values = self._positive_numbers(args, 2)
        if values is None:
            self._add_message("CAD Assistant", USAGE_CYLINDER, "error")
            return
        radius, height = values
        self._run_backend_command("create_cylinder", {"radius": radius, "height": height})

    def _cmd_sphere(self, args):
        values = self._positive_numbers(args, 1)
        if values is None:
            self._add_message("CAD Assistant", USAGE_SPHERE, "error")
            return
        self._run_backend_command("create_sphere", {"radius": values[0]})

    def _cmd_list(self, args):
        self._run_backend_command("list_objects", {})

    def _cmd_move(self, args):
        # The last three words are the position; everything before them is the name,
        # so names with spaces work: /move My Box 10 0 0
        if len(args) < 4:
            self._add_message("CAD Assistant", USAGE_MOVE, "error")
            return
        name = " ".join(args[:-3])
        try:
            x, y, z = (float(a) for a in args[-3:])
        except ValueError:
            self._add_message("CAD Assistant", USAGE_MOVE, "error")
            return
        if not all(math.isfinite(v) for v in (x, y, z)):
            self._add_message("CAD Assistant", USAGE_MOVE, "error")
            return
        self._run_backend_command("move_object", {"name": name, "x": x, "y": y, "z": z})

    def _cmd_delete(self, args):
        if not args:
            self._add_message("CAD Assistant", USAGE_DELETE, "error")
            return
        self._run_backend_command("delete_object", {"name": " ".join(args)})

    def _cmd_url(self, args):
        if not args:
            self._add_message(
                "CAD Assistant",
                "Backend URL: %s\nChange it with: /url http://127.0.0.1:9000" % backend_client.get_backend_url(),
            )
            return
        try:
            url = backend_client.set_backend_url(args[0])
        except ValueError as error:
            self._add_message("CAD Assistant", str(error), "error")
            return
        self._add_message("CAD Assistant", "Backend URL set to %s" % url)
        self._set_status("checking")
        self.check_backend()

    # ---------- talking to the backend (never blocks the UI) ----------

    def _run_backend_command(self, command, parameters):
        url = backend_client.get_backend_url()
        # The request runs in a background thread. daemon=True means a stuck
        # request can never keep FreeCAD from closing.
        threading.Thread(target=self._run_execute, args=(url, command, parameters), daemon=True).start()

    def _run_execute(self, url, command, parameters):
        """Background thread: ask the backend to validate the command."""
        result = backend_client.execute_command(url, command, parameters)
        self._results.put(("execute", result))

    def _on_execute_done(self, result):
        """UI thread: the backend answered. Now (and only now) change the FreeCAD document."""
        if not result["ok"]:
            self._add_message("CAD Assistant", result["message"], "error")
            return
        try:
            message = cad_actions.run_action(result["result"])
        except ValueError as error:  # an ordinary problem, e.g. "No object named 'Cone'": just say it
            self._add_message("CAD Assistant", str(error), "error")
            return
        except Exception as error:  # anything unexpected; never let it crash FreeCAD's UI
            self._add_message("CAD Assistant", "Could not run the action in FreeCAD: %s" % error, "error")
            return
        self._add_message("CAD Assistant", message)

    def check_backend(self):
        if self._checking:
            return
        self._checking = True
        threading.Thread(target=self._run_check, args=(backend_client.get_backend_url(),), daemon=True).start()

    def _run_check(self, url):
        """Background thread: call /health. Only queues a result; touches no widgets."""
        result = backend_client.check_health(url)
        result["url"] = url
        self._results.put(("check", result))

    def _on_check_done(self, result):
        """UI thread."""
        self._checking = False
        if result["url"] != backend_client.get_backend_url():
            self.check_backend()  # the URL changed while we were checking; check the new one
            return
        self._connected = result["ok"]
        self._last_message = result["message"]
        self._set_status("online" if result["ok"] else "offline", result["url"])

    def _drain_results(self):
        """UI thread, called by the timer: handle any results the threads have queued."""
        while True:
            try:
                kind, result = self._results.get_nowait()
            except queue.Empty:
                return
            try:
                if kind == "check":
                    self._on_check_done(result)
                else:
                    self._on_execute_done(result)
            except Exception as error:  # show problems in the chat instead of hiding them
                self._add_message("CAD Assistant", "Internal error: %s" % error, "error")

    def _set_status(self, state, url=""):
        address = url.split("://", 1)[-1]  # "http://127.0.0.1:8000" -> "127.0.0.1:8000"
        color, text = {
            "checking": (MUTED, "Checking backend..."),
            "online": (GREEN, "Backend connected (%s)" % address),
            "offline": (RED, self._last_message),  # explains why it is offline
        }[state]
        self.status_label.setText('<span style="color:%s;">●</span> %s' % (color, html.escape(text)))
        self.status_label.setToolTip(url)

    # ---------- check only while visible ----------

    def showEvent(self, event):
        super().showEvent(event)
        self.check_backend()
        self._check_timer.start(CHECK_INTERVAL_MS)
        self.input.setFocus()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._check_timer.stop()


# ---------- docking into FreeCAD ----------

def _find_dock():
    return FreeCADGui.getMainWindow().findChild(QtWidgets.QDockWidget, DOCK_NAME)


def show_panel():
    """Create the dock the first time, then just show it."""
    dock = _find_dock()
    if dock is None:
        main_window = FreeCADGui.getMainWindow()
        dock = QtWidgets.QDockWidget("CAD Assistant", main_window)
        dock.setObjectName(DOCK_NAME)  # FreeCAD needs a name to remember its position
        dock.setWidget(ChatPanel(dock))
        main_window.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        try:
            main_window.resizeDocks([dock], [PANEL_WIDTH], QtCore.Qt.Horizontal)  # a comfortable first width
        except Exception:
            pass  # cosmetic only
    dock.show()
    dock.raise_()
    return dock


def toggle_panel():
    dock = _find_dock()
    if dock is not None and dock.isVisible():
        dock.hide()
    else:
        show_panel()