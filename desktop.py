"""
CAD Automation Assistant - Desktop Client
=========================================
A clean, modern Windows desktop GUI built with Python and PySide6 (Qt).
Communicates with the FastAPI backend at http://127.0.0.1:8000 to validate and
route CAD automation commands.

Architectural Note:
-------------------
The existing backend validates parameters (e.g., verifying dimensions are positive)
and returns:
    {"action": "create_box", "executed": False, "message": "Validated. CAD software is not connected yet."}
This UI accurately reflects that CAD execution is pending and does NOT pretend
that 3D CAD solids are generated when they are only validated.

Ready for extension with:
  - FreeCAD (FreeCAD / Part Python API)
  - Siemens NX (NXOpen Python API)
"""

import sys
import json
import time
from datetime import datetime
import urllib.request
import urllib.error

from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer
from PySide6.QtGui import QFont, QColor, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QSplitter,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QGroupBox,
    QDoubleSpinBox,
    QTabWidget,
    QStatusBar,
    QFrame,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QMessageBox,
    QTextEdit,
)


# ==============================================================================
# Configuration & Constants
# ==============================================================================
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
APP_NAME = "CAD Automation Assistant"
APP_VERSION = "1.0.0"


# ==============================================================================
# Background Network Worker (Non-blocking HTTP Client)
# ==============================================================================
class BackendWorker(QThread):
    """
    Asynchronous worker thread to dispatch HTTP requests to the FastAPI backend.
    Ensures the PySide6 UI stays perfectly responsive even if the backend is slow
    or temporarily unreachable.
    """
    # Signals emitted upon completion
    request_finished = Signal(dict)

    def __init__(self, endpoint: str, method: str = "POST", payload: dict = None, parent=None):
        super().__init__(parent)
        self.endpoint = endpoint
        self.method = method.upper()
        self.payload = payload or {}

    def run(self):
        start_time = time.time()
        result = {
            "endpoint": self.endpoint,
            "method": self.method,
            "request_payload": self.payload,
            "success": False,
            "status_code": 0,
            "data": None,
            "error_message": "",
            "elapsed_ms": 0.0,
        }

        try:
            url = f"{DEFAULT_BACKEND_URL}{self.endpoint}"
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            data_bytes = None

            if self.method == "POST":
                data_bytes = json.dumps(self.payload).encode("utf-8")

            req = urllib.request.Request(url, data=data_bytes, headers=headers, method=self.method)

            # 5-second timeout for local API calls
            with urllib.request.urlopen(req, timeout=5) as response:
                result["status_code"] = response.status
                raw_body = response.read().decode("utf-8")
                try:
                    parsed_json = json.loads(raw_body)
                    result["data"] = parsed_json
                    result["success"] = True
                except json.JSONDecodeError:
                    result["data"] = {"raw": raw_body}
                    result["success"] = True

        except urllib.error.HTTPError as http_err:
            # Handles 400 Bad Request (such as ValueError/TypeError from actions.py)
            result["status_code"] = http_err.code
            err_body = http_err.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                # FastAPI typically returns {"detail": "..."}
                result["error_message"] = err_json.get("detail", str(err_json))
                result["data"] = err_json
            except Exception:
                result["error_message"] = f"HTTP {http_err.code}: {err_body or http_err.reason}"

        except urllib.error.URLError as url_err:
            result["status_code"] = 0
            result["error_message"] = (
                f"Connection Failed: Could not reach backend at {DEFAULT_BACKEND_URL}. "
                "Ensure FastAPI is running (e.g., 'uvicorn main:app --reload')."
            )

        except Exception as ex:
            result["status_code"] = 0
            result["error_message"] = f"Unexpected Error: {str(ex)}"

        result["elapsed_ms"] = round((time.time() - start_time) * 1000, 1)
        self.request_finished.emit(result)


# ==============================================================================
# Parameter Modal Dialog for "Create Box"
# ==============================================================================
class CreateBoxDialog(QDialog):
    """
    Dedicated dialog for visually inputting 3D box dimensions before dispatching.
    """
    def __init__(self, parent=None, default_l=100.0, default_w=50.0, default_h=25.0):
        super().__init__(parent)
        self.setWindowTitle("Create Box - Specify Dimensions")
        self.setFixedWidth(360)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        info_label = QLabel(
            "Enter the dimensions for the box feature.\n"
            "Values will be validated by the backend."
        )
        info_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        layout.addWidget(info_label)

        form_layout = QFormLayout()
        form_layout.setSpacing(10)

        self.spin_length = QDoubleSpinBox()
        self.spin_length.setRange(0.01, 100000.0)
        self.spin_length.setDecimals(2)
        self.spin_length.setSuffix(" mm")
        self.spin_length.setValue(default_l)

        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(0.01, 100000.0)
        self.spin_width.setDecimals(2)
        self.spin_width.setSuffix(" mm")
        self.spin_width.setValue(default_w)

        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(0.01, 100000.0)
        self.spin_height.setDecimals(2)
        self.spin_height.setSuffix(" mm")
        self.spin_height.setValue(default_h)

        form_layout.addRow("Length (X):", self.spin_length)
        form_layout.addRow("Width (Y):", self.spin_width)
        form_layout.addRow("Height (Z):", self.spin_height)

        layout.addLayout(form_layout)

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.button(QDialogButtonBox.Ok).setText("Send Command")
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_dimensions(self) -> dict:
        return {
            "length": float(self.spin_length.value()),
            "width": float(self.spin_width.value()),
            "height": float(self.spin_height.value()),
        }


# ==============================================================================
# Modern QSS Stylesheet
# ==============================================================================
DARK_THEME_QSS = """
QMainWindow, QDialog {
    background-color: #0f172a;
    color: #f8fafc;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
}

QWidget {
    color: #e2e8f0;
    font-size: 13px;
}

/* Group Boxes & Panels */
QGroupBox {
    border: 1px solid #334155;
    border-radius: 8px;
    margin-top: 24px;
    padding-top: 14px;
    background-color: #1e293b;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: #38bdf8;
}

/* Header & Banner */
QFrame#headerFrame {
    background-color: #1e293b;
    border-bottom: 1px solid #334155;
    padding: 10px;
}

/* Status Badges */
QLabel#statusBadgeOnline {
    background-color: #065f46;
    color: #34d399;
    border: 1px solid #059669;
    border-radius: 12px;
    padding: 3px 10px;
    font-weight: 600;
    font-size: 11px;
}

QLabel#statusBadgeOffline {
    background-color: #881337;
    color: #fda4af;
    border: 1px solid #e11d48;
    border-radius: 12px;
    padding: 3px 10px;
    font-weight: 600;
    font-size: 11px;
}

QLabel#statusBadgeWarning {
    background-color: #78350f;
    color: #fde047;
    border: 1px solid #d97706;
    border-radius: 12px;
    padding: 3px 10px;
    font-weight: 600;
    font-size: 11px;
}

/* Buttons */
QPushButton {
    background-color: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 13px;
}

QPushButton:hover {
    background-color: #1d4ed8;
}

QPushButton:pressed {
    background-color: #1e40af;
}

QPushButton:disabled {
    background-color: #334155;
    color: #64748b;
}

QPushButton#btnCheckStatus {
    background-color: #0284c7;
}
QPushButton#btnCheckStatus:hover {
    background-color: #0369a1;
}

QPushButton#btnCreateBox {
    background-color: #059669;
}
QPushButton#btnCreateBox:hover {
    background-color: #047857;
}

QPushButton#btnSecondary {
    background-color: #334155;
    color: #cbd5e1;
}
QPushButton#btnSecondary:hover {
    background-color: #475569;
}

/* Inputs & Spinners */
QLineEdit, QDoubleSpinBox, QTextEdit {
    background-color: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 8px 10px;
    color: #f8fafc;
    selection-background-color: #2563eb;
}

QLineEdit:focus, QDoubleSpinBox:focus, QTextEdit:focus {
    border: 1px solid #38bdf8;
}

/* Chat Browser */
QTextBrowser#chatBrowser {
    background-color: #090d16;
    border: 1px solid #1e293b;
    border-radius: 8px;
    padding: 12px;
}

/* Table Widget */
QTableWidget {
    background-color: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    gridline-color: #1e293b;
    color: #f1f5f9;
}

QTableWidget::item {
    padding: 6px;
    border-bottom: 1px solid #1e293b;
}

QTableWidget::item:selected {
    background-color: #1e3a8a;
    color: #ffffff;
}

QHeaderView::section {
    background-color: #1e293b;
    color: #94a3b8;
    padding: 8px;
    border: none;
    border-bottom: 2px solid #334155;
    font-weight: 600;
    font-size: 11px;
}

/* Tabs */
QTabWidget::pane {
    border: 1px solid #334155;
    border-radius: 6px;
    background-color: #1e293b;
}

QTabBar::tab {
    background-color: #0f172a;
    color: #94a3b8;
    padding: 8px 16px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    border: 1px solid #334155;
    border-bottom: none;
}

QTabBar::tab:selected {
    background-color: #1e293b;
    color: #38bdf8;
    font-weight: 600;
}

/* Splitter */
QSplitter::handle {
    background-color: #1e293b;
    width: 3px;
    height: 3px;
}

/* ScrollBars */
QScrollBar:vertical {
    border: none;
    background-color: #0f172a;
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background-color: #334155;
    border-radius: 4px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #475569;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


# ==============================================================================
# Main Desktop Window
# ==============================================================================
class CADAssistantWindow(QMainWindow):
    """
    Main Application Window providing:
      - Chat-style execution interface
      - Quick command buttons (Check Status, Create Box)
      - Execution history log table
      - Raw JSON payload inspector
      - Extensible CAD Engine guide (FreeCAD / Siemens NX)
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} - Windows Desktop v{APP_VERSION}")
        self.resize(1180, 780)
        self.setMinimumSize(900, 600)

        # Keep active worker references to prevent garbage collection
        self.active_workers = []

        self._build_ui()
        self._init_system_welcome()

        # Perform an initial health check on startup
        QTimer.singleShot(500, self.check_health_and_status)

    # --------------------------------------------------------------------------
    # UI Setup
    # --------------------------------------------------------------------------
    def _build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # 1. Header with Connection Badges
        header_frame = self._create_header_bar()
        main_layout.addWidget(header_frame)

        # 2. Main Body Splitter: Left (Chat + Actions) / Right (History + Inspector)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left_panel = self._create_left_panel()
        right_panel = self._create_right_panel()

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 55)
        splitter.setStretchFactor(1, 45)

        main_layout.addWidget(splitter)

        # 3. Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Target backend: http://127.0.0.1:8000")

    def _create_header_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("headerFrame")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 6, 10, 6)

        # Title / Icon
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_lbl = QLabel(f"📐 {APP_NAME}")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        subtitle_lbl = QLabel("FastAPI Backend Connector & Dispatcher")
        subtitle_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")
        title_box.addWidget(title_lbl)
        title_box.addWidget(subtitle_lbl)
        layout.addLayout(title_box)

        layout.addStretch()

        # Backend Connection Status Badge
        self.lbl_backend_badge = QLabel("Backend: Checking...")
        self.lbl_backend_badge.setObjectName("statusBadgeWarning")
        layout.addWidget(self.lbl_backend_badge)

        # CAD Engine Execution Status Badge
        self.lbl_cad_badge = QLabel("CAD Engine: Validation Mode (Not Connected)")
        self.lbl_cad_badge.setObjectName("statusBadgeWarning")
        self.lbl_cad_badge.setToolTip(
            "The backend currently validates commands only. "
            "FreeCAD or Siemens NX execution will take place when the CAD bridge is enabled."
        )
        layout.addWidget(self.lbl_cad_badge)

        # Ping / Refresh Button
        self.btn_refresh = QPushButton("🔄 Ping Health")
        self.btn_refresh.setObjectName("btnSecondary")
        self.btn_refresh.setToolTip("Check GET /health and status")
        self.btn_refresh.clicked.connect(self.check_health_and_status)
        layout.addWidget(self.btn_refresh)

        return frame

    def _create_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(10)

        # Chat Transcript Area
        chat_group = QGroupBox("Command & Response Transcript")
        chat_layout = QVBoxLayout(chat_group)
        chat_layout.setContentsMargins(10, 12, 10, 10)

        self.chat_browser = QTextBrowser()
        self.chat_browser.setObjectName("chatBrowser")
        self.chat_browser.setOpenExternalLinks(False)
        chat_layout.addWidget(self.chat_browser)

        layout.addWidget(chat_group, stretch=1)

        # Quick Actions Bar
        actions_group = QGroupBox("Quick Actions")
        actions_layout = QHBoxLayout(actions_group)
        actions_layout.setContentsMargins(10, 10, 10, 10)
        actions_layout.setSpacing(10)

        self.btn_status = QPushButton("🔍 Check Status")
        self.btn_status.setObjectName("btnCheckStatus")
        self.btn_status.setToolTip("Execute: {\"command\": \"status\", \"parameters\": {}}")
        self.btn_status.clicked.connect(self.action_check_status)
        actions_layout.addWidget(self.btn_status)

        self.btn_create_box = QPushButton("📦 Create Box...")
        self.btn_create_box.setObjectName("btnCreateBox")
        self.btn_create_box.setToolTip("Open dialog to specify length, width, height for box")
        self.btn_create_box.clicked.connect(self.action_open_create_box_dialog)
        actions_layout.addWidget(self.btn_create_box)

        self.btn_quick_box = QPushButton("⚡ Default Box (100×50×25)")
        self.btn_quick_box.setObjectName("btnSecondary")
        self.btn_quick_box.setToolTip("Quickly dispatch create_box with 100, 50, 25 mm")
        self.btn_quick_box.clicked.connect(lambda: self.action_create_box(100.0, 50.0, 25.0))
        actions_layout.addWidget(self.btn_quick_box)

        layout.addWidget(actions_group)

        # Message Input Area
        input_group = QGroupBox("Command Input")
        input_layout = QHBoxLayout(input_group)
        input_layout.setContentsMargins(10, 10, 10, 10)
        input_layout.setSpacing(8)

        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText(
            "Enter command (e.g., 'status', 'create_box 120 60 30', or JSON)..."
        )
        self.txt_input.returnPressed.connect(self.action_send_user_message)
        input_layout.addWidget(self.txt_input)

        self.btn_send = QPushButton("Send 🚀")
        self.btn_send.clicked.connect(self.action_send_user_message)
        input_layout.addWidget(self.btn_send)

        layout.addWidget(input_group)

        return panel

    def _create_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(10)

        # Tabs: Execution History, JSON Inspector, CAD Extension Architecture
        self.tabs = QTabWidget()

        # Tab 1: Execution History Table
        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        history_layout.setContentsMargins(8, 8, 8, 8)

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5)
        self.history_table.setHorizontalHeaderLabels([
            "Time", "Command", "Status", "CAD Executed?", "Backend Message"
        ])
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.history_table.itemClicked.connect(self._on_history_row_selected)
        history_layout.addWidget(self.history_table)

        hist_ctrl_layout = QHBoxLayout()
        lbl_hint = QLabel("💡 Click any row to view raw request/response JSON in Inspector")
        lbl_hint.setStyleSheet("font-size: 11px; color: #94a3b8;")
        hist_ctrl_layout.addWidget(lbl_hint)
        hist_ctrl_layout.addStretch()

        btn_clear = QPushButton("Clear History")
        btn_clear.setObjectName("btnSecondary")
        btn_clear.clicked.connect(self.action_clear_history)
        hist_ctrl_layout.addWidget(btn_clear)
        history_layout.addLayout(hist_ctrl_layout)

        self.tabs.addTab(history_tab, "📋 Execution History")

        # Tab 2: JSON Payload Inspector
        inspector_tab = QWidget()
        inspector_layout = QVBoxLayout(inspector_tab)
        inspector_layout.setContentsMargins(8, 8, 8, 8)

        inspector_layout.addWidget(QLabel("Request Payload sent to POST /execute:"))
        self.txt_inspector_req = QTextEdit()
        self.txt_inspector_req.setReadOnly(True)
        self.txt_inspector_req.setPlaceholderText("No request selected yet.")
        self.txt_inspector_req.setMaximumHeight(120)
        inspector_layout.addWidget(self.txt_inspector_req)

        inspector_layout.addWidget(QLabel("Raw Backend Response:"))
        self.txt_inspector_res = QTextEdit()
        self.txt_inspector_res.setReadOnly(True)
        self.txt_inspector_res.setPlaceholderText("No response selected yet.")
        inspector_layout.addWidget(self.txt_inspector_res)

        self.tabs.addTab(inspector_tab, "🔍 JSON Inspector")

        # Tab 3: CAD Extension Guide (FreeCAD & NX)
        cad_guide_tab = QWidget()
        guide_layout = QVBoxLayout(cad_guide_tab)
        guide_layout.setContentsMargins(12, 12, 12, 12)

        guide_browser = QTextBrowser()
        guide_browser.setHtml(self._get_cad_extension_html())
        guide_layout.addWidget(guide_browser)

        self.tabs.addTab(cad_guide_tab, "⚙️ FreeCAD / NX Extension")

        layout.addWidget(self.tabs)
        return panel

    # --------------------------------------------------------------------------
    # Welcome & Information Formatting
    # --------------------------------------------------------------------------
    def _init_system_welcome(self):
        welcome_html = f"""
        <div style="background-color: #1e293b; border-left: 4px solid #38bdf8; padding: 12px; border-radius: 6px; margin-bottom: 12px;">
            <b style="color: #38bdf8; font-size: 14px;">🚀 CAD Automation Assistant Desktop Ready</b><br>
            <span style="color: #cbd5e1; font-size: 12px;">
                Connected to FastAPI endpoint at <code>{DEFAULT_BACKEND_URL}</code>.<br>
                <b>Note on CAD Execution:</b> Backend actions validate your parameters (e.g. positive dimensions).
                Actual 3D CAD geometry generation is flagged as <code>executed: false</code> until FreeCAD or Siemens NX connector is linked.
            </span>
        </div>
        """
        self.chat_browser.append(welcome_html)

    def _get_cad_extension_html(self) -> str:
        return """
        <div style="font-family: 'Segoe UI', sans-serif; color: #e2e8f0; line-height: 1.5;">
            <h3 style="color: #38bdf8; margin-top: 0;">Modular CAD Integration Architecture</h3>
            <p style="font-size: 12px; color: #94a3b8;">
                Your backend is structured so that adding <b>FreeCAD</b> or <b>Siemens NX</b> can be done cleanly inside
                <code>actions.py</code> without changing this UI or API contract.
            </p>

            <h4 style="color: #34d399; margin-bottom: 4px;">1. FreeCAD Connector (Installed on this system):</h4>
            <div style="background-color: #0f172a; padding: 8px; border-radius: 4px; font-family: Consolas, monospace; font-size: 11px;">
                # In backend/actions.py (when FreeCAD is enabled):<br>
                import FreeCAD<br>
                import Part<br><br>
                doc = FreeCAD.ActiveDocument or FreeCAD.newDocument("CAD_Assistant")<br>
                box = doc.addObject("Part::Box", "AssistantBox")<br>
                box.Length, box.Width, box.Height = length, width, height<br>
                doc.recompute()<br>
                return {"action": "create_box", "executed": True, "message": "Box generated in FreeCAD."}
            </div>

            <h4 style="color: #60a5fa; margin-bottom: 4px; margin-top: 14px;">2. Siemens NX Connector (NXOpen):</h4>
            <div style="background-color: #0f172a; padding: 8px; border-radius: 4px; font-family: Consolas, monospace; font-size: 11px;">
                # In backend/actions.py (when NX is enabled):<br>
                import NXOpen<br>
                session = NXOpen.Session.GetSession()<br>
                workPart = session.Parts.Work<br>
                # Build block feature via NXOpen.Features.BlockFeatureBuilder<br>
                return {"action": "create_box", "executed": True, "message": "Box generated in Siemens NX."}
            </div>

            <p style="font-size: 11px; color: #facc15; margin-top: 14px;">
                ⚠️ <b>Truthful Execution Policy:</b> As long as <code>executed: false</code> is returned by the backend,
                this desktop interface will clearly indicate that the operation was validated only.
            </p>
        </div>
        """

    # --------------------------------------------------------------------------
    # Command Dispatching & Processing
    # --------------------------------------------------------------------------
    def dispatch_command(self, command: str, parameters: dict):
        """
        Dispatches a command payload to the backend POST /execute endpoint.
        """
        payload = {"command": command, "parameters": parameters}

        # Render user message bubble in chat
        timestamp = datetime.now().strftime("%H:%M:%S")
        param_str = json.dumps(parameters) if parameters else "{}"
        user_html = f"""
        <div style="margin: 8px 0; text-align: right;">
            <div style="display: inline-block; background-color: #1e3a8a; border: 1px solid #2563eb; color: #ffffff; padding: 8px 12px; border-radius: 8px; max-width: 85%; text-align: left;">
                <span style="font-size: 11px; color: #93c5fd;">🧑 User • {timestamp}</span><br>
                <b>Command:</b> <code>{command}</code><br>
                <span style="font-size: 11px; color: #bfdbfe;">Params: {param_str}</span>
            </div>
        </div>
        """
        self.chat_browser.append(user_html)
        self.chat_browser.moveCursor(QTextCursor.End)

        # Update status
        self.status_bar.showMessage(f"Sending '{command}' to backend...")
        self.btn_send.setEnabled(False)

        # Launch background worker
        worker = BackendWorker("/execute", method="POST", payload=payload, parent=self)
        worker.request_finished.connect(self._handle_execute_response)
        self.active_workers.append(worker)
        worker.start()

    def check_health_and_status(self):
        """
        Checks GET /health and queries backend status.
        """
        self.lbl_backend_badge.setText("Backend: Checking...")
        self.lbl_backend_badge.setObjectName("statusBadgeWarning")
        self.lbl_backend_badge.setStyleSheet("")  # re-evaluate QSS
        self.status_bar.showMessage("Checking backend /health...")

        worker = BackendWorker("/health", method="GET", payload={}, parent=self)
        worker.request_finished.connect(self._handle_health_response)
        self.active_workers.append(worker)
        worker.start()

    # --------------------------------------------------------------------------
    # Response Handlers
    # --------------------------------------------------------------------------
    @Slot(dict)
    def _handle_health_response(self, res: dict):
        # Clean up worker reference
        self.active_workers = [w for w in self.active_workers if not w.isFinished()]

        if res["success"]:
            self.lbl_backend_badge.setText("● Backend: Online (200 OK)")
            self.lbl_backend_badge.setObjectName("statusBadgeOnline")
            self.status_bar.showMessage(f"Backend connected at {DEFAULT_BACKEND_URL} ({res['elapsed_ms']} ms)")
        else:
            self.lbl_backend_badge.setText("● Backend: Offline")
            self.lbl_backend_badge.setObjectName("statusBadgeOffline")
            self.status_bar.showMessage(f"Backend offline: {res['error_message']}")

        # Reapply styles to the badge
        self.lbl_backend_badge.style().unpolish(self.lbl_backend_badge)
        self.lbl_backend_badge.style().polish(self.lbl_backend_badge)

    @Slot(dict)
    def _handle_execute_response(self, res: dict):
        # Clean up worker reference
        self.active_workers = [w for w in self.active_workers if not w.isFinished()]
        self.btn_send.setEnabled(True)

        timestamp = datetime.now().strftime("%H:%M:%S")
        req_payload = res.get("request_payload", {})
        command = req_payload.get("command", "unknown")
        params = req_payload.get("parameters", {})

        # Populate JSON Inspector with latest request and response
        self.txt_inspector_req.setPlainText(json.dumps(req_payload, indent=2))

        if res["success"]:
            data = res.get("data", {})
            raw_result = data.get("result", {})
            self.txt_inspector_res.setPlainText(json.dumps(data, indent=2))

            # Distinguish command types
            if command == "status":
                self._render_status_response(timestamp, raw_result, res["elapsed_ms"])
            elif command == "create_box":
                self._render_create_box_response(timestamp, raw_result, res["elapsed_ms"])
            else:
                self._render_generic_success_response(timestamp, command, raw_result, res["elapsed_ms"])

            # Add to History Table
            is_cad_exec = raw_result.get("executed", False) if isinstance(raw_result, dict) else False
            msg = raw_result.get("message", "Success") if isinstance(raw_result, dict) else str(raw_result)
            self._add_history_entry(
                timestamp=timestamp,
                command=command,
                status="200 OK",
                cad_executed="Yes" if is_cad_exec else "No (Validation Only)",
                message=msg,
                req=req_payload,
                res=data,
            )

        else:
            # Error condition (400 Bad Request or network error)
            error_msg = res.get("error_message", "Unknown error")
            status_str = f"Error {res['status_code']}" if res['status_code'] else "Net Error"
            self.txt_inspector_res.setPlainText(
                json.dumps(res.get("data") or {"error": error_msg}, indent=2)
            )

            self._render_error_response(timestamp, command, error_msg, res["status_code"])

            # Add to History Table
            self._add_history_entry(
                timestamp=timestamp,
                command=command,
                status=status_str,
                cad_executed="Failed",
                message=error_msg,
                req=req_payload,
                res=res.get("data") or {"error": error_msg},
            )

        self.chat_browser.moveCursor(QTextCursor.End)

    # --------------------------------------------------------------------------
    # Chat Bubble Renderers (Truthful execution reporting)
    # --------------------------------------------------------------------------
    def _render_status_response(self, timestamp: str, result: dict, elapsed: float):
        status_val = result.get("status", "unknown")
        cad_connected = result.get("cad_connected", False)

        cad_badge_color = "#34d399" if cad_connected else "#f59e0b"
        cad_badge_text = "Connected" if cad_connected else "Disconnected (Validation Only)"

        html = f"""
        <div style="margin: 8px 0;">
            <div style="background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 10px 14px; max-width: 90%;">
                <div style="font-size: 11px; color: #94a3b8; margin-bottom: 6px;">
                    🤖 <b>CAD Assistant</b> • {timestamp} • <span style="color: #38bdf8;">{elapsed} ms</span>
                </div>
                <div style="font-size: 13px; font-weight: 600; color: #38bdf8; margin-bottom: 6px;">
                    📊 System & CAD Status
                </div>
                <table style="font-size: 12px; color: #cbd5e1; line-height: 1.6;">
                    <tr>
                        <td style="padding-right: 12px; color: #94a3b8;">Backend Status:</td>
                        <td><b style="color: #34d399;">{status_val.upper()}</b></td>
                    </tr>
                    <tr>
                        <td style="padding-right: 12px; color: #94a3b8;">CAD Integration:</td>
                        <td><b style="color: {cad_badge_color};">{cad_badge_text}</b></td>
                    </tr>
                </table>
            </div>
        </div>
        """
        self.chat_browser.append(html)

    def _render_create_box_response(self, timestamp: str, result: dict, elapsed: float):
        dims = result.get("dimensions", {})
        l_val = dims.get("length", 0)
        w_val = dims.get("width", 0)
        h_val = dims.get("height", 0)
        executed = result.get("executed", False)
        backend_msg = result.get("message", "")

        # Truthful UI badge: If executed is False, display explicit validation-only notice!
        if not executed:
            cad_banner = f"""
            <div style="background-color: #451a03; border-left: 4px solid #f59e0b; padding: 8px 10px; border-radius: 4px; margin-top: 8px;">
                <b style="color: #fde047;">⚠️ Validated Only (CAD Engine Pending)</b><br>
                <span style="font-size: 11px; color: #fef08a;">
                    Backend verified dimensions are positive.<br>
                    <i>Message: "{backend_msg}"</i>
                </span>
            </div>
            """
        else:
            cad_banner = f"""
            <div style="background-color: #064e3b; border-left: 4px solid #34d399; padding: 8px 10px; border-radius: 4px; margin-top: 8px;">
                <b style="color: #6ee7b7;">✅ CAD Geometry Created</b><br>
                <span style="font-size: 11px; color: #a7f3d0;">{backend_msg}</span>
            </div>
            """

        html = f"""
        <div style="margin: 8px 0;">
            <div style="background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 10px 14px; max-width: 90%;">
                <div style="font-size: 11px; color: #94a3b8; margin-bottom: 6px;">
                    🤖 <b>CAD Assistant</b> • {timestamp} • <span style="color: #38bdf8;">{elapsed} ms</span>
                </div>
                <div style="font-size: 13px; font-weight: 600; color: #38bdf8; margin-bottom: 6px;">
                    📦 Box Feature Result
                </div>
                <table style="font-size: 12px; color: #cbd5e1; line-height: 1.5;">
                    <tr>
                        <td style="padding-right: 12px; color: #94a3b8;">Dimensions (L × W × H):</td>
                        <td><b>{l_val} mm × {w_val} mm × {h_val} mm</b></td>
                    </tr>
                </table>
                {cad_banner}
            </div>
        </div>
        """
        self.chat_browser.append(html)

    def _render_generic_success_response(self, timestamp: str, command: str, result: dict, elapsed: float):
        html = f"""
        <div style="margin: 8px 0;">
            <div style="background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 10px 14px; max-width: 90%;">
                <div style="font-size: 11px; color: #94a3b8; margin-bottom: 6px;">
                    🤖 <b>CAD Assistant</b> • {timestamp} • <span style="color: #38bdf8;">{elapsed} ms</span>
                </div>
                <div style="font-size: 13px; font-weight: 600; color: #34d399; margin-bottom: 6px;">
                    ✅ Response for '{command}'
                </div>
                <pre style="background-color: #0f172a; padding: 8px; border-radius: 4px; font-size: 11px; color: #f8fafc;">{json.dumps(result, indent=2)}</pre>
            </div>
        </div>
        """
        self.chat_browser.append(html)

    def _render_error_response(self, timestamp: str, command: str, error_msg: str, status_code: int):
        code_badge = f"HTTP {status_code}" if status_code else "NETWORK ERROR"
        html = f"""
        <div style="margin: 8px 0;">
            <div style="background-color: #3b0712; border: 1px solid #991b1b; border-radius: 8px; padding: 10px 14px; max-width: 90%;">
                <div style="font-size: 11px; color: #f87171; margin-bottom: 6px;">
                    ⚠️ <b>Command Execution Error</b> • {timestamp} • <b>{code_badge}</b>
                </div>
                <div style="font-size: 13px; font-weight: 600; color: #fecaca; margin-bottom: 4px;">
                    Command '{command}' rejected
                </div>
                <div style="font-size: 12px; color: #fee2e2;">
                    <b>Detail:</b> {error_msg}
                </div>
            </div>
        </div>
        """
        self.chat_browser.append(html)

    # --------------------------------------------------------------------------
    # History Table Management
    # --------------------------------------------------------------------------
    def _add_history_entry(self, timestamp: str, command: str, status: str,
                           cad_executed: str, message: str, req: dict, res: dict):
        row = self.history_table.rowCount()
        self.history_table.insertRow(row)

        item_time = QTableWidgetItem(timestamp)
        item_cmd = QTableWidgetItem(command)
        item_status = QTableWidgetItem(status)
        item_cad = QTableWidgetItem(cad_executed)
        item_msg = QTableWidgetItem(message)

        # Color coding
        if "200" in status or status == "Success":
            item_status.setForeground(QColor("#34d399"))
        else:
            item_status.setForeground(QColor("#f87171"))

        if "No" in cad_executed:
            item_cad.setForeground(QColor("#f59e0b"))
        elif "Yes" in cad_executed:
            item_cad.setForeground(QColor("#34d399"))
        else:
            item_cad.setForeground(QColor("#ef4444"))

        # Store full payload objects inside UserRole for inspection
        item_time.setData(Qt.UserRole, {"request": req, "response": res})

        self.history_table.setItem(row, 0, item_time)
        self.history_table.setItem(row, 1, item_cmd)
        self.history_table.setItem(row, 2, item_status)
        self.history_table.setItem(row, 3, item_cad)
        self.history_table.setItem(row, 4, item_msg)

        # Auto scroll to bottom
        self.history_table.scrollToBottom()

    def _on_history_row_selected(self, item: QTableWidgetItem):
        row = item.row()
        time_item = self.history_table.item(row, 0)
        data = time_item.data(Qt.UserRole)
        if data:
            self.txt_inspector_req.setPlainText(json.dumps(data.get("request", {}), indent=2))
            self.txt_inspector_res.setPlainText(json.dumps(data.get("response", {}), indent=2))
            # Switch to inspector tab
            self.tabs.setCurrentIndex(1)

    def action_clear_history(self):
        self.history_table.setRowCount(0)
        self.txt_inspector_req.clear()
        self.txt_inspector_res.clear()
        self.status_bar.showMessage("Execution history cleared.")

    # --------------------------------------------------------------------------
    # User Action Slots
    # --------------------------------------------------------------------------
    @Slot()
    def action_check_status(self):
        self.dispatch_command("status", {})

    @Slot()
    def action_open_create_box_dialog(self):
        dialog = CreateBoxDialog(self)
        if dialog.exec():
            dims = dialog.get_dimensions()
            self.action_create_box(dims["length"], dims["width"], dims["height"])

    def action_create_box(self, length: float, width: float, height: float):
        params = {
            "length": float(length),
            "width": float(width),
            "height": float(height),
        }
        self.dispatch_command("create_box", params)

    @Slot()
    def action_send_user_message(self):
        raw_text = self.txt_input.text().strip()
        if not raw_text:
            return

        self.txt_input.clear()

        # 1. Check if user passed raw JSON string
        if raw_text.startswith("{") and raw_text.endswith("}"):
            try:
                parsed = json.loads(raw_text)
                if isinstance(parsed, dict) and "command" in parsed:
                    self.dispatch_command(parsed["command"], parsed.get("parameters", {}))
                    return
            except Exception:
                pass  # Fall through to natural parsing

        # 2. Natural language / shorthand parsing
        parts = raw_text.split()
        cmd_lower = parts[0].lower()

        if cmd_lower in ("status", "health", "check_status"):
            self.dispatch_command("status", {})

        elif cmd_lower in ("box", "create_box", "createbox"):
            # Syntax: "box 100 50 25" or "box"
            if len(parts) >= 4:
                try:
                    l = float(parts[1])
                    w = float(parts[2])
                    h = float(parts[3])
                    self.action_create_box(l, w, h)
                    return
                except ValueError:
                    pass
            # If no numbers provided, launch the modal dialog for convenience
            self.action_open_create_box_dialog()

        else:
            # Fallback: Send directly as command name to backend
            # The backend will route it and return 400 'Unknown command' if invalid
            self.dispatch_command(raw_text, {})


# ==============================================================================
# Application Entry Point
# ==============================================================================
def main():
    # Enable high-DPI scaling
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_THEME_QSS)

    window = CADAssistantWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
