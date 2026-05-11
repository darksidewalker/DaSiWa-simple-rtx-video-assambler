import sys, os, subprocess, math, textwrap, shutil, shlex
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QListWidget, QComboBox,
    QLabel, QFileDialog, QTextEdit, QSpinBox
)
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtCore import QUrl, QProcess, QElapsedTimer


def _resolve_binary(name):
    """Return the path to ffmpeg/ffprobe, preferring an override env var, then a
    system path that contains NVENC (Arch/CachyOS), then whatever is on PATH.

    On Linuxbrew systems the brew copy may shadow the system one even though only
    the system build has NVENC. Prefer /usr/bin/<name> when it exists."""
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


class VideoTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DaSiWa-simple-rtx-video-assambler")
        self.resize(980, 840)
        self.setAcceptDrops(True)
        self.files = []
        self.last_cmd = ""
        self.default_dir = str(Path.home() / "Videos")
        self.ffmpeg_proc = None
        self.encode_timer = QElapsedTimer()
        # Cached aspect ratio (w, h) of the first input, refreshed when the file list
        # changes. Used by the "Auto (from first input)" tile aspect option.
        self._auto_aspect = None
        self._auto_aspect_source = None  # path the cache was built from
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        layout.addWidget(QLabel("Videos (Drag & Drop to add, select to reorder/remove):"))

        list_hbox = QHBoxLayout()
        self.file_list = QListWidget()
        list_hbox.addWidget(self.file_list)

        reorder_vbox = QVBoxLayout()
        self.up_btn = QPushButton("Move Up")
        self.down_btn = QPushButton("Move Down")
        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.setStyleSheet("background-color: #441111; color: white;")

        self.up_btn.clicked.connect(lambda: self.reorder_item(-1))
        self.down_btn.clicked.connect(lambda: self.reorder_item(1))
        self.remove_btn.clicked.connect(self.remove_selected)

        reorder_vbox.addWidget(self.up_btn)
        reorder_vbox.addWidget(self.down_btn)
        reorder_vbox.addWidget(self.remove_btn)
        reorder_vbox.addStretch()
        list_hbox.addLayout(reorder_vbox)
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
            "Inside Video",
            "Top of Video",
        ])
        self.text_mode_combo.setCurrentText("Inside Video")

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
        # Populated dynamically based on encoder choice.
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
        # Populated from the file list whenever it changes.
        row4.addWidget(self.audio_source_combo, stretch=1)
        settings_grid.addLayout(row4)

        self.audio_mode_combo.currentTextChanged.connect(self.update_audio_source_state)
        self.file_list.model().rowsInserted.connect(lambda *args: self.refresh_audio_source_list())
        self.file_list.model().rowsRemoved.connect(lambda *args: self.refresh_audio_source_list())
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
        self.file_list.model().rowsInserted.connect(lambda *args: self.update_resolution_preview())
        self.file_list.model().rowsRemoved.connect(lambda *args: self.update_resolution_preview())
        self.update_resolution_preview()
        self.log_area.setText(
            f"Using ffmpeg:  {FFMPEG_BIN}\nUsing ffprobe: {FFPROBE_BIN}\n"
            f"(Override with FFMPEG_BIN / FFPROBE_BIN env vars.)"
        )

    def reorder_item(self, direction):
        curr_row = self.file_list.currentRow()
        if curr_row == -1:
            return
        new_row = curr_row + direction
        if 0 <= new_row < self.file_list.count():
            self.files.insert(new_row, self.files.pop(curr_row))
            item = self.file_list.takeItem(curr_row)
            self.file_list.insertItem(new_row, item)
            self.file_list.setCurrentRow(new_row)

    def remove_selected(self):
        curr_row = self.file_list.currentRow()
        if curr_row != -1:
            self.files.pop(curr_row)
            self.file_list.takeItem(curr_row)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            f = url.toLocalFile()
            if f.lower().endswith((".mp4", ".mkv", ".mov", ".avi", ".webm")) and f not in self.files:
                self.files.append(f)
                self.file_list.addItem(os.path.basename(f))

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Videos", self.default_dir,
            "Videos (*.mp4 *.mkv *.mov *.avi *.webm)"
        )
        for f in files:
            if f and f not in self.files:
                self.files.append(f)
                self.file_list.addItem(os.path.basename(f))

    def clear_files(self):
        self.files = []
        self.file_list.clear()
        self.open_folder_btn.setVisible(False)
        self.copy_btn.setVisible(False)

    def open_output_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_output_dir))

    def copy_command(self):
        QApplication.clipboard().setText(self.last_cmd)

    @staticmethod
    def force_even(n):
        n = int(round(float(n)))
        return n if n % 2 == 0 else n - 1

    @staticmethod
    def escape_drawtext(text):
        return (
            text.replace('\\', r'\\')
                .replace(':', r'\:')
                .replace("'", r"\'")
                .replace('[', r'\[')
                .replace(']', r'\]')
                .replace(',', r'\,')
                .replace('%', r'\%')
        )


    @staticmethod
    def wrap_filename_for_box(text, max_chars):
        wrapped = textwrap.wrap(
            text,
            width=max(6, int(max_chars)),
            break_long_words=True,
            break_on_hyphens=False,
        )
        return "\\n".join(wrapped) if wrapped else text

    def refresh_auto_aspect(self):
        """Probe the first file to capture its native aspect ratio. Cheap (one ffprobe
        call) and only re-runs when the first file path changes."""
        if not self.files:
            self._auto_aspect = None
            self._auto_aspect_source = None
            return
        first = self.files[0]
        if first == self._auto_aspect_source and self._auto_aspect is not None:
            return
        try:
            probe = subprocess.run(
                [FFPROBE_BIN, '-v', 'error', '-select_streams', 'v:0',
                 '-show_entries', 'stream=width,height',
                 '-of', 'csv=p=0', first],
                capture_output=True, text=True, timeout=15,
            )
            parts = probe.stdout.strip().split(',')
            if len(parts) >= 2:
                w = int(parts[0])
                h = int(parts[1])
                if w > 0 and h > 0:
                    self._auto_aspect = (w, h)
                    self._auto_aspect_source = first
                    return
        except Exception:
            pass
        # Probe failed; fall back to a sane default so the tool keeps working.
        self._auto_aspect = None
        self._auto_aspect_source = first

    def get_layout_metrics(self):
        aspect_map = {
            "16:9 (Landscape)": (16, 9),
            "4:3 (Landscape)": (4, 3),
            "1:1 (Square)": (1, 1),
            "9:16 (Portrait)": (9, 16),
            "4:5 (Portrait)": (4, 5),
            "1376:1760 (Old)": (1376, 1760),
        }

        target_h = self.force_even(self.res_combo.currentText())
        num = max(len(self.files), 1)
        mode = self.layout_combo.currentText()
        if mode == "Single Row":
            rows, cols_per_row = 1, num
        elif mode == "Single Column":
            rows, cols_per_row = num, 1
        else:  # Grid (Max 2 Cols)
            rows, cols_per_row = math.ceil(num / 2), 2

        tile_h = self.force_even(target_h / rows)

        aspect_choice = self.aspect_combo.currentText()
        if aspect_choice.startswith("Auto"):
            # Use the first input's native aspect; fall back to 16:9 if we couldn't probe.
            ar_w, ar_h = self._auto_aspect if self._auto_aspect else (16, 9)
        else:
            ar_w, ar_h = aspect_map[aspect_choice]
        tile_w = self.force_even(tile_h * (ar_w / ar_h))

        font_size = self.font_spin.value()
        text_mode = self.text_mode_combo.currentText()
        header_h = self.force_even(max(font_size * 2 + 20, 36)) if text_mode == "Top of Video" else 0
        box_h = tile_h + header_h

        canvas_w = tile_w * cols_per_row
        canvas_h = box_h * rows

        if mode == "Grid (Max 2 Cols)" and len(self.files) > 0:
            canvas_w = tile_w * min(2, len(self.files))

        return {
            "rows": rows,
            "cols_per_row": cols_per_row,
            "tile_w": tile_w,
            "tile_h": tile_h,
            "header_h": header_h,
            "box_h": box_h,
            "canvas_w": canvas_w,
            "canvas_h": canvas_h,
        }

    def update_preset_choices(self):
        encoder = self.encoder_combo.currentText()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        if encoder.startswith("av1_nvenc"):
            self.preset_combo.addItems(["p1", "p2", "p3", "p4", "p5", "p6", "p7"])
            self.preset_combo.setCurrentText("p6")
        else:
            # libsvtav1: 0 = slowest/best quality, 13 = fastest. 6 is a common balanced default.
            self.preset_combo.addItems([str(i) for i in range(0, 14)])
            self.preset_combo.setCurrentText("6")
        self.preset_combo.blockSignals(False)

    def refresh_audio_source_list(self):
        # Keep the per-file picker in sync with self.files.
        prev_index = self.audio_source_combo.currentIndex()
        self.audio_source_combo.blockSignals(True)
        self.audio_source_combo.clear()
        for i, f in enumerate(self.files):
            self.audio_source_combo.addItem(f"{i + 1}. {os.path.basename(f)}")
        if 0 <= prev_index < self.audio_source_combo.count():
            self.audio_source_combo.setCurrentIndex(prev_index)
        self.audio_source_combo.blockSignals(False)

    def update_audio_source_state(self):
        self.audio_source_combo.setEnabled(
            self.audio_mode_combo.currentText() == "From specific file"
        )

    # NVENC AV1 minimum frame dimensions (NVENC SDK floor; varies slightly by codec
    # and GPU generation, but 160x64 is a safe lower bound used as the rejected-by-driver line).
    NVENC_MIN_W = 160
    NVENC_MIN_H = 64

    def nvenc_dimension_warning(self, canvas_w, canvas_h):
        """Return a warning string if NVENC is selected and dimensions are too small, else ''."""
        if not self.encoder_combo.currentText().startswith("av1_nvenc"):
            return ""
        if canvas_w < self.NVENC_MIN_W or canvas_h < self.NVENC_MIN_H:
            return (
                f" | WARNING: NVENC requires at least {self.NVENC_MIN_W}x{self.NVENC_MIN_H}. "
                f"Raise Output Height, change Layout, or switch Encoder to libsvtav1 (CPU)."
            )
        return ""

    def update_resolution_preview(self):
        self.refresh_auto_aspect()
        m = self.get_layout_metrics()
        header_text = f" + {m['header_h']} px header" if m["header_h"] > 0 else ""
        clip_count = len(self.files)
        warning = self.nvenc_dimension_warning(m["canvas_w"], m["canvas_h"])

        # Show the resolved aspect when Auto is chosen so the user knows what got detected.
        aspect_note = ""
        if self.aspect_combo.currentText().startswith("Auto"):
            if self._auto_aspect:
                aspect_note = f"   |   Detected aspect: {self._auto_aspect[0]}x{self._auto_aspect[1]}"
            elif self.files:
                aspect_note = "   |   Aspect probe failed, defaulting to 16:9"

        self.resolution_info_label.setText(
            f"Clips: {clip_count}   |   Final output: {m['canvas_w']}x{m['canvas_h']}   |   "
            f"Each video tile: {m['tile_w']}x{m['tile_h']}{header_text}{aspect_note}{warning}"
        )
        if warning:
            self.resolution_info_label.setStyleSheet("color: #ff7777; padding: 4px 0; font-weight: bold;")
        else:
            self.resolution_info_label.setStyleSheet("color: #cccccc; padding: 4px 0;")

    def process_video(self):
        if not self.files:
            return

        # Pre-flight: catch NVENC minimum-dimension violations before ffmpeg does.
        pre_metrics = self.get_layout_metrics()
        warning = self.nvenc_dimension_warning(pre_metrics["canvas_w"], pre_metrics["canvas_h"])
        if warning:
            self.set_status(
                "error",
                f"Output is {pre_metrics['canvas_w']}x{pre_metrics['canvas_h']}, below NVENC's "
                f"{self.NVENC_MIN_W}x{self.NVENC_MIN_H} minimum. Raise Output Height, change Layout, "
                f"or switch Encoder to libsvtav1 (CPU).",
            )
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save WebM",
            os.path.join(self.default_dir, "output.webm"),
            "WebM (*.webm)"
        )
        if not save_path:
            return

        self.last_output_dir = os.path.dirname(save_path)
        self.last_output_path = save_path
        # Reset everything from any previous run.
        self.open_folder_btn.setVisible(False)
        self.copy_btn.setVisible(False)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.log_area.clear()
        self.set_status("encoding", "Encoding...")

        metrics = self.get_layout_metrics()
        num = len(self.files)
        rows = metrics["rows"]
        cols_per_row = metrics["cols_per_row"]
        tile_h = metrics["tile_h"]
        tile_w = metrics["tile_w"]
        header_h = metrics["header_h"]
        box_h = metrics["box_h"]

        font_size = self.font_spin.value()
        fit_mode = self.fit_combo.currentText()
        text_mode = self.text_mode_combo.currentText()

        encoder_choice = self.encoder_combo.currentText()
        use_nvenc = encoder_choice.startswith("av1_nvenc")
        hwaccel_args = ["-hwaccel", "cuda"] if use_nvenc else []

        input_args = []
        filters = []

        for i, f in enumerate(self.files):
            input_args.extend(hwaccel_args + ["-i", f])
            raw_name = os.path.splitext(os.path.basename(f))[0]
            max_text_w = max(tile_w - 30, 80)
            estimated_char_w = max(font_size * 0.60, 1)
            max_chars = max(6, int(max_text_w / estimated_char_w))
            wrapped_name = self.wrap_filename_for_box(raw_name, max_chars)
            fname = self.escape_drawtext(wrapped_name)

            inside_text = (
                f"drawtext=text='{fname}':fontcolor=white:fontsize={font_size}:"
                f"shadowcolor=black:shadowx=2:shadowy=2:line_spacing=4:x=15:y=15"
            )
            header_text = (
                f"drawtext=text='{fname}':fontcolor=white:fontsize={font_size}:"
                f"shadowcolor=black:shadowx=2:shadowy=2:line_spacing=4:"
                f"x=max((w-text_w)/2\\,10):y=max(({header_h}-text_h)/2\\,4)"
            )

            draw_inside = (text_mode == "Inside Video")

            if fit_mode == "Contain (No crop, pad if needed)":
                # Keep label attached to the actual image area, not the black padding.
                base = (
                    f"[{i}:v]"
                    f"scale=w={tile_w}:h={tile_h}:force_original_aspect_ratio=decrease,"
                    f"setsar=1"
                )
                if draw_inside:
                    base += f",{inside_text}"
                base += f",pad={tile_w}:{tile_h}:(ow-iw)/2:(oh-ih)/2:color=black"
            elif fit_mode == "Cover (Fill tile, crop overflow)":
                base = (
                    f"[{i}:v]"
                    f"scale=w={tile_w}:h={tile_h}:force_original_aspect_ratio=increase,"
                    f"crop={tile_w}:{tile_h},"
                    f"setsar=1"
                )
                if draw_inside:
                    base += f",{inside_text}"
            else:  # Stretch (Old behavior)
                base = (
                    f"[{i}:v]"
                    f"scale={tile_w}:{tile_h},"
                    f"setsar=1"
                )
                if draw_inside:
                    base += f",{inside_text}"

            if header_h > 0:
                # Top-of-video mode: show filename only in the black strip above the video.
                base += f",pad={tile_w}:{box_h}:0:{header_h}:color=black,{header_text}"

            filters.append(base + f"[v{i}]")

        row_labels = []
        for r in range(rows):
            start = r * cols_per_row
            end = min((r + 1) * cols_per_row, num)
            count = end - start
            vids = "".join([f"[v{i}]" for i in range(start, end)])

            if count == cols_per_row and count >= 2:
                filters.append(f"{vids}hstack=inputs={count}:shortest=1[r{r}]")
            elif count == 1:
                # Single tile in this row: just pass through, no hstack (which requires >=2).
                filters.append(f"{vids}null[r{r}]")
            else:
                full_row_w = tile_w * cols_per_row
                filters.append(f"{vids}pad=w={full_row_w}:h={box_h}:x=(ow-iw)/2:y=0:color=black[r{r}]")
            row_labels.append(f"[r{r}]")

        f_graph = ";".join(filters)
        if len(row_labels) > 1:
            f_graph += f";{''.join(row_labels)}vstack=inputs={len(row_labels)}:shortest=1[outv]"
        else:
            f_graph += f";{row_labels[0]}null[outv]"

        # Audio: build the audio graph based on the user's selected mode.
        audio_mode = self.audio_mode_combo.currentText()
        audio_indices = []

        if audio_mode == "None (strip audio)":
            pass
        elif audio_mode == "From specific file":
            picked = self.audio_source_combo.currentIndex()
            if 0 <= picked < len(self.files):
                # Probe just the picked file; if it has no audio, fall through to no-audio output.
                try:
                    probe = subprocess.run(
                        [FFPROBE_BIN, '-v', 'error', '-select_streams', 'a:0',
                         '-show_entries', 'stream=codec_type', '-of', 'csv=p=0',
                         self.files[picked]],
                        capture_output=True, text=True, timeout=15,
                    )
                    if probe.stdout.strip() == 'audio':
                        audio_indices = [picked]
                except Exception:
                    pass
        else:
            # Auto: probe each input, mix tracks from clips that actually have audio.
            for i, f in enumerate(self.files):
                try:
                    probe = subprocess.run(
                        [FFPROBE_BIN, '-v', 'error', '-select_streams', 'a:0',
                         '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', f],
                        capture_output=True, text=True, timeout=15,
                    )
                    if probe.stdout.strip() == 'audio':
                        audio_indices.append(i)
                except Exception:
                    pass

        audio_args = []
        if audio_indices:
            if len(audio_indices) == 1:
                # Single audio source: just resample/normalize sample rate, no mix.
                f_graph += f";[{audio_indices[0]}:a]aresample=async=1[outa]"
            else:
                a_inputs = "".join(f"[{i}:a]" for i in audio_indices)
                # amix with normalize=1 (default) avoids clipping by dividing volumes by N.
                f_graph += (
                    f";{a_inputs}amix=inputs={len(audio_indices)}:duration=shortest:dropout_transition=0[outa]"
                )
            audio_args = ["-map", "[outa]", "-c:a", "libopus", "-b:a", "160k"]
        else:
            audio_args = ["-an"]

        if use_nvenc:
            video_codec_args = [
                "-c:v", "av1_nvenc",
                "-preset", self.preset_combo.currentText(),
                "-cq", str(self.cq_spin.value()),
                "-b:v", "0",
            ]
        else:
            # libsvtav1 uses -crf and integer presets; range matches our spinbox 1-51 well enough.
            video_codec_args = [
                "-c:v", "libsvtav1",
                "-preset", self.preset_combo.currentText(),
                "-crf", str(self.cq_spin.value()),
                "-b:v", "0",
            ]

        ffmpeg_args = (
            ["-y"]
            + input_args
            + ["-filter_complex", f_graph, "-map", "[outv]"]
            + audio_args
            + video_codec_args
            + ["-pix_fmt", "yuv420p", "-shortest", save_path]
        )
        # Human-readable command for the Copy Cmd button and for debugging.
        self.last_cmd = shlex.join([FFMPEG_BIN] + ffmpeg_args)

        # Launch asynchronously so the GUI stays responsive and stderr streams live.
        self.ffmpeg_proc = QProcess(self)
        self.ffmpeg_proc.setProcessChannelMode(QProcess.MergedChannels)
        self.ffmpeg_proc.readyReadStandardOutput.connect(self.on_ffmpeg_output)
        self.ffmpeg_proc.finished.connect(self.on_ffmpeg_finished)
        self.ffmpeg_proc.errorOccurred.connect(self.on_ffmpeg_error)
        self.encode_timer.start()
        self.ffmpeg_proc.start(FFMPEG_BIN, ffmpeg_args)

    STATUS_STYLES = {
        "idle":     ("#1a1a1a", "#888888"),
        "encoding": ("#3a2c0a", "#ffc24a"),
        "success":  ("#103a10", "#7fff7f"),
        "error":    ("#3a1010", "#ff7777"),
        "canceled": ("#2a2a2a", "#cccccc"),
    }

    def set_status(self, kind, text):
        bg, fg = self.STATUS_STYLES.get(kind, self.STATUS_STYLES["idle"])
        self.status_banner.setText(text)
        self.status_banner.setStyleSheet(
            f"background-color: {bg}; color: {fg}; padding: 8px 12px; "
            f"border-radius: 4px; font-weight: bold;"
        )

    def on_ffmpeg_output(self):
        if not self.ffmpeg_proc:
            return
        chunk = bytes(self.ffmpeg_proc.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        if not chunk:
            return
        # FFmpeg uses \r to overwrite the progress line; split it out so the log
        # doesn't drown in repeated lines while still keeping the latest status.
        self.log_area.moveCursor(QTextCursor.End)
        self.log_area.insertPlainText(chunk)
        self.log_area.moveCursor(QTextCursor.End)

        # Keep the banner ticking with elapsed time.
        elapsed_s = self.encode_timer.elapsed() // 1000
        mm, ss = divmod(elapsed_s, 60)
        self.set_status("encoding", f"Encoding... {mm:02d}:{ss:02d} elapsed")

    def on_ffmpeg_finished(self, exit_code, exit_status):
        if getattr(self, "_user_canceled", False):
            self._user_canceled = False
            self.ffmpeg_proc = None
            return
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        elapsed_s = self.encode_timer.elapsed() // 1000
        mm, ss = divmod(elapsed_s, 60)
        elapsed_str = f"{mm:02d}:{ss:02d}"

        if exit_status == QProcess.CrashExit:
            self.set_status("error", f"FFmpeg crashed after {elapsed_str}.")
            self.log_area.append("\n--- ENCODE CRASHED ---")
        elif exit_code == 0:
            try:
                size_mb = os.path.getsize(self.last_output_path) / (1024 * 1024)
                size_str = f" ({size_mb:.1f} MB)"
            except OSError:
                size_str = ""
            fname = os.path.basename(self.last_output_path)
            self.set_status(
                "success",
                f"Done in {elapsed_str}. Saved {fname}{size_str}.",
            )
            self.log_area.append(f"\n--- SUCCESS in {elapsed_str} ---")
            self.open_folder_btn.setVisible(True)
            self.copy_btn.setVisible(True)
        else:
            self.set_status(
                "error",
                f"FFmpeg exited with code {exit_code} after {elapsed_str}. See log below.",
            )
            self.log_area.append(f"\n--- ERROR (exit code {exit_code}) ---")
        self.ffmpeg_proc = None

    def on_ffmpeg_error(self, error):
        # errorOccurred fires for FailedToStart, etc. finished may or may not follow.
        if error == QProcess.FailedToStart:
            self.set_status(
                "error",
                f"Could not launch ffmpeg. Check that '{FFMPEG_BIN}' exists and is executable.",
            )
            self.log_area.append(f"\nFailed to start: {FFMPEG_BIN}")
            self.start_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.ffmpeg_proc = None

    def cancel_encode(self):
        if not self.ffmpeg_proc:
            return
        self._user_canceled = True
        self.set_status("canceled", "Canceling...")
        self.ffmpeg_proc.terminate()
        # Give it a moment to clean up, then force-kill if it ignores us.
        if not self.ffmpeg_proc.waitForFinished(2000):
            self.ffmpeg_proc.kill()
            self.ffmpeg_proc.waitForFinished(2000)
        self.set_status("canceled", "Canceled.")
        self.log_area.append("\n--- CANCELED ---")
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoTool()
    window.show()
    sys.exit(app.exec())
