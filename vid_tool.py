#!/usr/bin/env python3
"""Simple RT Video Assembler - Qt6 UI with native Drag & Drop reordering."""
import sys, os, subprocess, math, textwrap, shutil, shlex, datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QFileDialog, QTextEdit, QLineEdit,
    QScrollArea, QFrame, QComboBox, QSpinBox
)
from PySide6.QtCore import QUrl, QProcess, QElapsedTimer, Qt, Signal, QEvent, QMimeData, QPoint, QByteArray
from PySide6.QtGui import QDesktopServices, QTextCursor, QDrag, QMouseEvent, QCursor


def _resolve_binary(name):
    """Return the path to ffmpeg/ffprobe, preferring env override, then system path, then PATH."""
    env_key = f"{name.upper()}_BIN"
    if os.environ.get(env_key):
        return os.environ[env_key]
    system_path = f"/usr/bin/{name}"
    if os.path.exists(system_path):
        return system_path
    found = shutil.which(name)
    return found or name


FFMPEG_BIN = _resolve_binary("ffmpeg")
FFPROBE_BIN = _resolve_binary("ffprobe")


class VideoRow(QWidget):
    """Single row: drag handle | filename label | custom text field | remove button."""

    delete_requested = Signal(str)
    selected = Signal()

    def __init__(self, file_path, tool=None, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.file_path = file_path
        self._is_selected = False
        self._tool = tool
        self._press_pos = QPoint(0, 0)
        self._drag_started = False

        raw_name = os.path.splitext(os.path.basename(file_path))[0]

        hbox = QHBoxLayout(self)
        hbox.setContentsMargins(3, 2, 3, 2)
        hbox.setSpacing(6)

        # Drag handle icon
        drag_lbl = QLabel("⠿")
        drag_lbl.setStyleSheet("color: #666666; font-size: 13px; min-width: 16px;")
        drag_lbl.setCursor(Qt.PointingHandCursor)
        drag_lbl.setToolTip("Ziehen zum Umordnen")
        hbox.addWidget(drag_lbl)

        # File name label
        name_lbl = QLabel(raw_name)
        name_lbl.setStyleSheet("color: #aaaaaa; min-width: 120px;")
        name_lbl.setToolTip(file_path)
        hbox.addWidget(name_lbl, stretch=1)

        # Custom text overlay field
        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText("Kein Text")
        self.text_edit.setMaxLength(50)
        self.text_edit.setMaximumHeight(24)
        self.text_edit.setMinimumWidth(180)
        self.text_edit.setStyleSheet(
            "QLineEdit { background: #1a1a1a; color: #ddd; border: 1px solid #333; "
            "border-radius: 3px; padding: 2px 6px; }"
            "QLineEdit:focus { border-color: #76b900; }"
        )
        self.text_edit.installEventFilter(self)
        hbox.addWidget(self.text_edit, stretch=3)

        # Remove button
        rm_btn = QPushButton("✕")
        rm_btn.setFixedSize(26, 26)
        rm_btn.setStyleSheet(
            "QPushButton { background: #441111; color: white; border: none; "
            "border-radius: 13px; font-size: 11px; }"
            "QPushButton:hover { background: #662222; }"
        )
        rm_btn.setToolTip("Entfernen")
        rm_btn.clicked.connect(lambda checked=False, fp=self.file_path: self.delete_requested.emit(fp))
        hbox.addWidget(rm_btn)

    def mousePressEvent(self, event):
        """Click selects the row and records press position."""
        if event.button() == Qt.LeftButton:
            self.selected.emit()
            self._press_pos = event.globalPos()
            self._drag_started = False
        # DO NOT call super() — Qt's internal drag handling would hijack the press

    def mouseMoveEvent(self, event):
        """Start drag once movement exceeds threshold."""
        if not (event.buttons() & Qt.LeftButton) or self._drag_started:
            return
        distance = (event.globalPos() - self._press_pos).manhattanLength()
        if distance > QApplication.startDragDistance():
            self._launch_drag()

    def _launch_drag(self):
        """Launch a native QDrag so other rows can receive it via dropEvent."""
        self._drag_started = True
        self.setStyleSheet("background-color: #666666; opacity: 0.5;")

        mime = self.mimeData()

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec_(Qt.MoveAction)

    def mimeData(self):
        """Return MIME data used for internal row reordering."""
        mime = QMimeData()
        mime.setData("application/x-videofile-url", self.file_path.encode("utf-8"))
        return mime

    def mouseReleaseEvent(self, event):
        """Clean up drag state after QDrag completes."""
        if not self._drag_started:
            super().mouseReleaseEvent(event)
            return
        # QDrag.exec_() already handled the reorder in dropEvent
        self._drag_started = False
        self.setStyleSheet("")
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event):
        """Accept own-file drags (internal reorder) and external file drops."""
        if event.mimeData().hasFormat("application/x-videofile-url"):
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-videofile-url") or event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        event.accept()

    def dropEvent(self, event):
        """Handle internal reorder or external file drops."""
        if event.mimeData().hasFormat("application/x-videofile-url"):
            # Another row was dropped here → internal reorder
            src_bytes = event.mimeData().data("application/x-videofile-url")
            src_path = bytes(src_bytes).decode("utf-8")
            if src_path != self.file_path:
                self._do_reorder(src_path, self.file_path)
            event.acceptProposedAction()
            return

        # External file drop
        if event.mimeData().hasUrls() and self._tool:
            self._tool.add_video_files(
                url.toLocalFile()
                for url in event.mimeData().urls()
                if url.toLocalFile().lower().endswith((".mp4", ".mkv", ".mov", ".avi", ".webm"))
            )
            event.acceptProposedAction()
            return
        event.ignore()

    def _do_reorder(self, src_path, dest_path):
        """Move src_path to the position where dest_path was."""
        files = self._tool.files
        src_idx = files.index(src_path)
        dest_idx = files.index(dest_path)
        if src_idx == dest_idx:
            return
        files.pop(src_idx)
        # After removal, insert at the original destination index.
        # This works for both directions:
        # - Forward (src < dest): dest shifted left, so dest_idx now points past it;
        #   inserting there places src right after dest's original spot.
        # - Backward (src > dest): dest unchanged, inserting there puts src at dest's spot.
        files.insert(dest_idx, src_path)
        self._tool.select_row(dest_idx)
        self._tool.rebuild_list_widgets()
        self._tool.refresh_audio_source_list()
        self._tool.update_resolution_preview()

    def eventFilter(self, obj, event):
        """Capture click events on text input to trigger selection."""
        if obj is self.text_edit and event.type() == QEvent.MouseButtonPress:
            self.selected.emit()
            return False
        return super().eventFilter(obj, event)

    def set_selected(self, selected):
        """Update selection state and visual styling."""
        self._is_selected = selected
        if selected:
            self.setStyleSheet("background-color: #444444;")
        else:
            self.setStyleSheet("")

    def get_display_text(self):
        """Return the custom text. Returns empty string if no custom text entered."""
        text = self.text_edit.text().strip()
        return text


class VideoDropZone(QFrame):
    """Small dedicated drop target for adding video files from the file manager."""

    def __init__(self, tool, parent=None):
        super().__init__(parent)
        self._tool = tool
        self.setAcceptDrops(True)
        self.setMinimumSize(190, 64)
        self.setMaximumWidth(260)
        self.setStyleSheet(self._style(False))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(0)

        self.drop_label = QLabel("Drop video files here\nMP4, MKV, MOV, AVI, WEBM")
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label.setStyleSheet(
            "background-color: #151515; color: #a8a8a8; border: none; "
            "border-radius: 3px; padding: 8px 10px; font-size: 11px;"
        )
        layout.addWidget(self.drop_label)

    def _style(self, active):
        background = "#16210f" if active else "transparent"
        return f"background-color: {background}; border: none;"

    def dragEnterEvent(self, event):
        if self._has_video_urls(event):
            self.setStyleSheet(self._style(True))
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._has_video_urls(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self._style(False))
        event.accept()

    def dropEvent(self, event):
        self.setStyleSheet(self._style(False))
        files = self._video_files_from_event(event)
        if files:
            self._tool.add_video_files(files)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _has_video_urls(self, event):
        return bool(self._video_files_from_event(event))

    def _video_files_from_event(self, event):
        if not event.mimeData().hasUrls():
            return []
        videos = []
        for url in event.mimeData().urls():
            f = url.toLocalFile()
            if f.lower().endswith((".mp4", ".mkv", ".mov", ".avi", ".webm")):
                videos.append(f)
        return videos


class VideoTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DaSiWa-simple-rtx-video-assambler")
        self.resize(980, 840)
        self.setAcceptDrops(True)
        self.files = []
        self.row_widgets = {}  # Maps file_path -> VideoRow instance
        self._selected_idx = -1  # Track selected row index
        self.last_cmd = ""
        self.default_dir = str(Path.home() / "Videos")
        self.ffmpeg_proc = None
        self.encode_timer = QElapsedTimer()
        self._auto_aspect = None
        self._auto_aspect_source = None
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        list_hbox = QHBoxLayout()
        self.drop_zone = VideoDropZone(self)
        list_hbox.addWidget(self.drop_zone, stretch=0)

        # Scrollable list area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.list_container)
        list_hbox.addWidget(self.scroll_area, stretch=1)

        layout.addLayout(list_hbox)

        btn_frame = QHBoxLayout()
        self.add_btn = QPushButton("Add Manually")
        self.add_btn.clicked.connect(self.add_files)
        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.clicked.connect(self.clear_files)
        btn_frame.addWidget(self.add_btn)
        btn_frame.addWidget(self.clear_btn)
        layout.addLayout(btn_frame)

        settings_grid = QVBoxLayout()

        row1 = QHBoxLayout()
        self.res_combo = QComboBox()
        self.res_combo.addItems(["720", "1080", "1440", "2160"])
        self.res_combo.setCurrentText("1080")

        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["Grid (Max 2 Cols)", "Single Row", "Single Column"])
        self.layout_combo.setCurrentText("Single Row")

        self.aspect_combo = QComboBox()
        self.aspect_combo.addItems([
            "Auto (from first input)",
            "16:9 (Landscape)",
            "4:3 (Landscape)",
            "1:1 (Square)",
            "9:16 (Portrait)",
            "4:5 (Portrait)",
            "1376:1760 (Old)",
        ])
        self.aspect_combo.setCurrentText("Auto (from first input)")

        row1.addWidget(QLabel("Output Height:"))
        row1.addWidget(self.res_combo)
        row1.addWidget(QLabel("Layout:"))
        row1.addWidget(self.layout_combo)
        row1.addWidget(QLabel("Tile Aspect:"))
        row1.addWidget(self.aspect_combo)
        settings_grid.addLayout(row1)

        row2 = QHBoxLayout()
        self.fit_combo = QComboBox()
        self.fit_combo.addItems([
            "Contain (No crop, pad if needed)",
            "Cover (Fill tile, crop overflow)",
            "Stretch (Old behavior)",
        ])
        self.fit_combo.setCurrentText("Contain (No crop, pad if needed)")

        self.text_mode_combo = QComboBox()
        self.text_mode_combo.addItems([
            "Top Left",
            "Top Center",
            "Top Right",
            "Bottom Left",
            "Bottom Center",
            "Bottom Right",
        ])
        self.text_mode_combo.setCurrentText("Top Left")

        row2.addWidget(QLabel("Fit Mode:"))
        row2.addWidget(self.fit_combo)
        row2.addWidget(QLabel("Text Mode:"))
        row2.addWidget(self.text_mode_combo)
        settings_grid.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Quality (CQ):"))
        self.cq_spin = QSpinBox()
        self.cq_spin.setRange(1, 51)
        self.cq_spin.setValue(25)
        row3.addWidget(self.cq_spin)

        row3.addWidget(QLabel("Font Size:"))
        self.font_spin = QSpinBox()
        self.font_spin.setRange(10, 200)
        self.font_spin.setValue(22)
        row3.addWidget(self.font_spin)

        row3.addWidget(QLabel("Encoder:"))
        self.encoder_combo = QComboBox()
        self.encoder_combo.addItems(["av1_nvenc (RTX)", "libsvtav1 (CPU)"])
        self.encoder_combo.setCurrentText("av1_nvenc (RTX)")
        row3.addWidget(self.encoder_combo)

        row3.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        row3.addWidget(self.preset_combo)
        settings_grid.addLayout(row3)
        layout.addLayout(settings_grid)

        self.encoder_combo.currentTextChanged.connect(self.update_preset_choices)
        self.update_preset_choices()

        row4 = QHBoxLayout()
        row4.addWidget(QLabel("Audio:"))
        self.audio_mode_combo = QComboBox()
        self.audio_mode_combo.addItems([
            "Auto (mix all that have sound)",
            "None (strip audio)",
            "From specific file",
        ])
        self.audio_mode_combo.setCurrentText("Auto (mix all that have sound)")
        row4.addWidget(self.audio_mode_combo)

        self.audio_source_combo = QComboBox()
        self.audio_source_combo.setEnabled(False)
        row4.addWidget(self.audio_source_combo, stretch=1)
        settings_grid.addLayout(row4)

        self.audio_mode_combo.currentTextChanged.connect(self.update_audio_source_state)
        self.refresh_audio_source_list()
        self.update_audio_source_state()

        self.resolution_info_label = QLabel("")
        self.resolution_info_label.setStyleSheet("color: #cccccc; padding: 4px 0;")
        self.resolution_info_label.setWordWrap(True)
        layout.addWidget(self.resolution_info_label)

        self.status_banner = QLabel("Idle.")
        self.status_banner.setStyleSheet(
            "background-color: #1a1a1a; color: #888888; padding: 8px 12px; "
            "border-radius: 4px; font-weight: bold;"
        )
        layout.addWidget(self.status_banner)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("background-color: #0a0a0a; color: #00ff41; font-family: 'Courier New';")
        layout.addWidget(self.log_area)

        start_row = QHBoxLayout()
        self.start_btn = QPushButton("START AV1 ENCODE")
        self.start_btn.setStyleSheet("background-color: #76b900; color: black; font-weight: bold; height: 50px;")
        self.start_btn.clicked.connect(self.process_video)
        start_row.addWidget(self.start_btn, stretch=4)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet("background-color: #441111; color: white; font-weight: bold; height: 50px;")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_encode)
        start_row.addWidget(self.cancel_btn, stretch=1)
        layout.addLayout(start_row)

        action_hbox = QHBoxLayout()
        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.setVisible(False)
        self.open_folder_btn.clicked.connect(self.open_output_folder)
        self.copy_btn = QPushButton("Copy Cmd")
        self.copy_btn.setVisible(False)
        self.copy_btn.clicked.connect(self.copy_command)
        action_hbox.addWidget(self.open_folder_btn)
        action_hbox.addWidget(self.copy_btn)
        layout.addLayout(action_hbox)

        self.res_combo.currentTextChanged.connect(self.update_resolution_preview)
        self.layout_combo.currentTextChanged.connect(self.update_resolution_preview)
        self.aspect_combo.currentTextChanged.connect(self.update_resolution_preview)
        self.text_mode_combo.currentTextChanged.connect(self.update_resolution_preview)
        self.font_spin.valueChanged.connect(self.update_resolution_preview)
        self.encoder_combo.currentTextChanged.connect(self.update_resolution_preview)
        self.update_resolution_preview()
        self.log_area.setText(
            f"Using ffmpeg:  {FFMPEG_BIN}\nUsing ffprobe: {FFPROBE_BIN}\n"
            f"(Override with FFMPEG_BIN / FFPROBE_BIN env vars.)"
        )

    def rebuild_list_widgets(self):
        """Re-render the list container from self.files order."""
        existing_text = {
            fp: row.get_display_text()
            for fp, row in self.row_widgets.items()
        }
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        self.row_widgets.clear()
        for i, fp in enumerate(self.files):
            row = VideoRow(fp, tool=self)
            if existing_text.get(fp):
                row.text_edit.setText(existing_text[fp])
            row.delete_requested.connect(self.on_delete_from_row)
            row.selected.connect(lambda idx=i: self.select_row(idx))
            row.set_selected(i == self._selected_idx)
            self.list_layout.addWidget(row)
            self.row_widgets[fp] = row

    def select_row(self, idx):
        """Select a row by index, updating visual feedback."""
        for w in self.row_widgets.values():
            w.set_selected(False)
        if 0 <= idx < len(self.files):
            self._selected_idx = idx
            fp = self.files[idx]
            if fp in self.row_widgets:
                self.row_widgets[fp].set_selected(True)

    def on_delete_from_row(self, file_path):
        """Handle deletion signal from VideoRow."""
        if file_path in self.files:
            idx = self.files.index(file_path)
            self.files.pop(idx)
            if self._selected_idx >= len(self.files):
                self._selected_idx = max(0, len(self.files) - 1)
            else:
                self.select_row(self._selected_idx)
            self.rebuild_list_widgets()

    def add_files(self):
        """Open file dialog to add videos manually."""
        files, _ = QFileDialog.getOpenFileNames(
            self, "Videos hinzufügen", self.default_dir,
            "Video Files (*.mp4 *.mkv *.mov *.avi *.webm)"
        )
        if files:
            self.add_video_files(files)

    def add_video_files(self, files):
        """Append new video files and refresh dependent UI state."""
        added = False
        for fp in files:
            if fp.lower().endswith((".mp4", ".mkv", ".mov", ".avi", ".webm")) and fp not in self.files:
                self.files.append(fp)
                added = True
        if added:
            if self._selected_idx == -1:
                self._selected_idx = 0
            self.rebuild_list_widgets()
            self.refresh_audio_source_list()
            self.update_resolution_preview()

    def clear_files(self):
        """Remove all videos from the list."""
        self.files.clear()
        self._selected_idx = -1
        self.rebuild_list_widgets()
        self.refresh_audio_source_list()
        self.update_resolution_preview()

    def update_audio_source_state(self):
        """Enable/disable audio source dropdown based on mode."""
        mode = self.audio_mode_combo.currentText()
        enabled = "specific" in mode.lower()
        self.audio_source_combo.setEnabled(enabled)
        if enabled:
            self.refresh_audio_source_list()

    def refresh_audio_source_list(self):
        """Populate audio source dropdown with available video files."""
        self.audio_source_combo.blockSignals(True)
        self.audio_source_combo.clear()
        self.audio_source_combo.addItem("-- None --")
        for fp in self.files:
            name = os.path.basename(fp)
            self.audio_source_combo.addItem(name, fp)
        self.audio_source_combo.blockSignals(False)

    def update_preset_choices(self):
        """Update preset dropdown based on encoder selection."""
        encoder = self.encoder_combo.currentText()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        if "nvenc" in encoder.lower():
            self.preset_combo.addItems([
                "Performance", "P1 (Fastest)", "P2", "P3", "P4", "P5 (Default)",
                "P6", "P7", "P8 (Slow)", "P9 (Slower)", "Quality",
            ])
        else:
            self.preset_combo.addItems([
                "Speed 8 (Fastest)", "Speed 6", "Speed 4", "Speed 3 (Default)",
                "Speed 2", "Speed 1", "Quality",
            ])
        self.preset_combo.blockSignals(False)

    def update_resolution_preview(self):
        """Show estimated output resolution based on current settings."""
        if not self.files:
            self.resolution_info_label.setText("Keine Videos geladen.")
            return

        try:
            heights = []
            widths = []
            for fp in self.files[:4]:  # Check first 4 at most
                cmd = [FFPROBE_BIN, "-v", "error", "-select_streams", "v:0",
                       "-show_entries", "stream=width,height", "-of", "csv=p=0", fp]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and result.stdout.strip():
                    parts = result.stdout.strip().split(",")
                    if len(parts) == 2:
                        widths.append(int(parts[0]))
                        heights.append(int(parts[1]))

            if not heights:
                self.resolution_info_label.setText("Auflösung nicht ermittelbar.")
                return

            avg_w = sum(widths) // len(widths)
            avg_h = sum(heights) // len(heights)

            out_h = int(self.res_combo.currentText())
            aspect = self.aspect_combo.currentText()

            # Calculate output width based on aspect ratio
            if aspect.startswith("Auto"):
                out_w = round(avg_w * out_h / avg_h)
            elif aspect.startswith("16:9"):
                out_w = round(out_h * 16 / 9)
            elif aspect.startswith("4:3"):
                out_w = round(out_h * 4 / 3)
            elif aspect.startswith("1:1"):
                out_w = out_h
            elif aspect.startswith("9:16"):
                out_w = round(out_h * 9 / 16)
            elif aspect.startswith("4:5"):
                out_w = round(out_h * 4 / 5)
            elif aspect.startswith("1376"):
                out_w = round(out_h * 1376 / 1760)
            else:
                out_w = avg_w

            n = len(self.files)
            cols = 2 if "Grid" in self.layout_combo.currentText() else 1
            rows = math.ceil(n / cols)

            final_w = out_w * cols
            final_h = out_h * rows

            self.resolution_info_label.setText(
                f"{n} Video(s), je {avg_w}x{avg_h}px → "
                f"Ausgabe: {final_w}x{final_h}px @ {out_h}p"
            )
        except Exception as e:
            self.resolution_info_label.setText(f"Fehler bei Auflösungsberechnung: {e}")

    def process_video(self):
        """Build and execute the ffmpeg command for encoding."""
        if not self.files:
            self.status_banner.setText("Fehler: Keine Videos ausgewählt!")
            return

        self.status_banner.setText("Encoding läuft...")
        self.start_btn.setEnabled(False)
        self.encode_timer.start()

        output_dir = Path.home() / "Videos" / "rve-output"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"assembled_{timestamp}.mp4"

        # Determine layout dimensions
        n = len(self.files)
        out_h = int(self.res_combo.currentText())

        # Determine tile width from the selected aspect ratio.
        aspect = self.aspect_combo.currentText()
        if aspect.startswith("16:9"):
            out_w = round(out_h * 16 / 9)
        elif aspect.startswith("4:3"):
            out_w = round(out_h * 4 / 3)
        elif aspect.startswith("1:1"):
            out_w = out_h
        elif aspect.startswith("9:16"):
            out_w = round(out_h * 9 / 16)
        elif aspect.startswith("4:5"):
            out_w = round(out_h * 4 / 5)
        elif aspect.startswith("1376"):
            out_w = round(out_h * 1376 / 1760)
        else:
            out_w = round(out_h * 16 / 9)

        # Add text overlay if any video has custom text
        text_overlays = []
        for i, fp in enumerate(self.files):
            row = self.row_widgets.get(fp)
            if row:
                text = row.get_display_text()
                if text:
                    text_overlays.append((i, text))

        # Audio mode (used later in command build)
        audio_mode = self.audio_mode_combo.currentText()

        # Encoder settings
        encoder = self.encoder_combo.currentText()
        preset = self.preset_combo.currentText()
        cq = self.cq_spin.value()

        if "nvenc" in encoder.lower():
            codec = "av1_nvenc"
            # Map UI labels to actual nvenc preset values (p1=fastest, p9=slowest/best)
            nvenc_presets = {
                "Performance": "p5",
                "P1 (Fastest)": "p1",
                "P2": "p2",
                "P3": "p3",
                "P4": "p4",
                "P5 (Default)": "p5",
                "P6": "p6",
                "P7": "p7",
                "P8 (Slow)": "p8",
                "P9 (Slower)": "p9",
                "Quality": "p9",
            }
            preset_val = nvenc_presets.get(preset, "p5")
            quality_flag = "-cq"
            quality_val = str(cq)
        else:
            codec = "libsvtav1"
            # Extract numeric speed tier from labels like "Speed 8 (Fastest)" -> "8"
            # Quality maps to 0 (slowest/best)
            if preset == "Quality":
                preset_val = "0"
            else:
                preset_val = str(int(preset.split()[1]))
            quality_flag = "-crf"
            quality_val = str(cq)

        # Build full command
        cmd = [FFMPEG_BIN, "-y"]
        for fp in self.files:
            cmd.extend(["-i", fp])

        # Build filter_complex for the selected layout (+ optional audio mix).
        fit_mode = self.fit_combo.currentText().lower()
        filter_parts = []
        video_labels = []
        text_by_index = dict(text_overlays)

        for i in range(n):
            if "cover" in fit_mode:
                chain = (
                    f"[{i}:v:0]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
                    f"crop={out_w}:{out_h}"
                )
            elif "stretch" in fit_mode:
                chain = f"[{i}:v:0]scale={out_w}:{out_h}"
            else:
                chain = (
                    f"[{i}:v:0]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                    f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2"
                )

            if i in text_by_index:
                escaped = (
                    text_by_index[i]
                    .replace("\\", "\\\\")
                    .replace(":", "\\:")
                    .replace("'", "\\'")
                    .replace(",", "\\,")
                )
                mode = self.text_mode_combo.currentText().lower()
                if "bottom" in mode:
                    y_expr = "h-th-10"
                elif "center" in mode:
                    y_expr = "(h-th)/2"
                else:
                    y_expr = "10"
                if "right" in mode:
                    x_expr = "w-tw-10"
                elif "left" in mode:
                    x_expr = "10"
                else:
                    x_expr = "(w-tw)/2"
                chain += (
                    f",drawtext=text='{escaped}':fontsize={self.font_spin.value()}:fontcolor=white:borderw=2:bordercolor=black:x={x_expr}:y={y_expr}"
                )

            label = f"v{i}"
            filter_parts.append(f"{chain}[{label}]")
            video_labels.append(f"[{label}]")

        layout_mode = self.layout_combo.currentText()
        if n == 1:
            filter_parts.append(f"{video_labels[0]}null[vout]")
        elif "Grid" in layout_mode:
            positions = []
            for i in range(n):
                x = "0" if i % 2 == 0 else "w0"
                row = i // 2
                y = "0" if row == 0 else "+".join("h0" for _ in range(row))
                positions.append(f"{x}_{y}")
            filter_parts.append(
                f"{''.join(video_labels)}xstack=inputs={n}:layout={'|'.join(positions)}:fill=black[vout]"
            )
        elif "Single Row" in layout_mode:
            filter_parts.append(f"{''.join(video_labels)}hstack=inputs={n}[vout]")
        else:
            filter_parts.append(f"{''.join(video_labels)}vstack=inputs={n}[vout]")

        filter_parts_str = ";".join(filter_parts)

        audio_map = None
        if "none" in audio_mode.lower():
            pass  # No audio
        elif "specific" in audio_mode.lower():
            src = self.audio_source_combo.currentData()
            if src:
                audio_map = f"{self.files.index(src)}:a:0"
        else:
            # Auto mix all audio streams
            audio_streams = "".join(f"[{i}:a:0]" for i in range(n))
            amix = f"amix=inputs={n}:duration=longest[audio_out]"
            filter_parts_str += f";{audio_streams}{amix}"
            audio_map = "[audio_out]"

        # Assemble command parts
        if filter_parts_str:
            cmd.extend(["-filter_complex", filter_parts_str])
        if audio_map:
            cmd.extend(["-map", "[vout]", "-map", audio_map])
        else:
            cmd.extend(["-map", "[vout]"])

        cmd.extend([
            "-c:v", codec,
            quality_flag, quality_val,
            "-preset", preset_val,
            "-pix_fmt", "yuv420p",
        ])
        if audio_map:
            cmd.extend(["-c:a", "aac"])
        cmd.extend([str(output_file)])

        self.last_cmd = " ".join(shlex.quote(a) for a in cmd)
        self.log_area.append(f"\n{'='*60}\nCMD: {self.last_cmd}\n{'='*60}")

        self.ffmpeg_proc = QProcess()
        self.ffmpeg_proc.readyReadStandardOutput.connect(self.on_ffmpeg_stdout)
        self.ffmpeg_proc.readyReadStandardError.connect(self.on_ffmpeg_stderr)
        self.ffmpeg_proc.finished.connect(self.on_ffmpeg_finished)

        self.ffmpeg_proc.start(cmd[0], cmd[1:])

    def on_ffmpeg_stdout(self):
        data = bytes(self.ffmpeg_proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.log_area.append(data.rstrip())

    def on_ffmpeg_stderr(self):
        data = bytes(self.ffmpeg_proc.readAllStandardError()).decode("utf-8", errors="replace")
        self.log_area.append(data.rstrip())

    def on_ffmpeg_finished(self, exit_code, exit_status):
        elapsed = self.encode_timer.elapsed() / 1000.0
        if exit_code == 0:
            self.status_banner.setText(f"Encoding fertig! ({elapsed:.1f}s)")
        else:
            self.status_banner.setText(f"Encoding fehlgeschlagen (Exit: {exit_code})")
        self.start_btn.setEnabled(True)
        self.ffmpeg_proc = None

    def cancel_encode(self):
        """Kill the running ffmpeg process."""
        if self.ffmpeg_proc:
            self.ffmpeg_proc.terminate()
            self.ffmpeg_proc.waitForFinished(3000)
            if self.ffmpeg_proc.state() != QProcess.NotRunning:
                self.ffmpeg_proc.kill()
            self.ffmpeg_proc = None
            self.status_banner.setText("Abgebrochen.")
            self.start_btn.setEnabled(True)

    def open_output_folder(self):
        """Open the output folder in the system file manager."""
        output_dir = Path.home() / "Videos" / "rve-output"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_dir)))

    def copy_command(self):
        """Copy the last command to clipboard."""
        if self.last_cmd:
            QApplication.clipboard().setText(self.last_cmd)
            self.status_banner.setText("Befehl in die Zwischenablage kopiert!")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoTool()
    window.show()
    sys.exit(app.exec())