import sys, os, subprocess, math, textwrap
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QListWidget, QComboBox,
    QLabel, QFileDialog, QTextEdit, QSpinBox
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl


class VideoTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DaSiWa-simple-rtx-video-assambler")
        self.resize(980, 840)
        self.setAcceptDrops(True)
        self.files = []
        self.last_cmd = ""
        self.default_dir = str(Path.home() / "Videos")
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
        self.layout_combo.addItems(["Grid (Max 2 Cols)", "Single Row"])
        self.layout_combo.setCurrentText("Single Row")

        self.aspect_combo = QComboBox()
        self.aspect_combo.addItems([
            "9:16 (Portrait)",
            "4:5 (Portrait)",
            "1376:1760 (Old)",
        ])
        self.aspect_combo.setCurrentText("9:16 (Portrait)")

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

        row3.addWidget(QLabel("NVENC Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["p1", "p2", "p3", "p4", "p5", "p6", "p7"])
        self.preset_combo.setCurrentText("p6")
        row3.addWidget(self.preset_combo)
        settings_grid.addLayout(row3)
        layout.addLayout(settings_grid)

        self.resolution_info_label = QLabel("")
        self.resolution_info_label.setStyleSheet("color: #cccccc; padding: 4px 0;")
        self.resolution_info_label.setWordWrap(True)
        layout.addWidget(self.resolution_info_label)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("background-color: #0a0a0a; color: #00ff41; font-family: 'Courier New';")
        layout.addWidget(self.log_area)

        self.start_btn = QPushButton("START AV1 ENCODE")
        self.start_btn.setStyleSheet("background-color: #76b900; color: black; font-weight: bold; height: 50px;")
        self.start_btn.clicked.connect(self.process_video)
        layout.addWidget(self.start_btn)

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
        self.file_list.model().rowsInserted.connect(lambda *args: self.update_resolution_preview())
        self.file_list.model().rowsRemoved.connect(lambda *args: self.update_resolution_preview())
        self.update_resolution_preview()

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

    def get_layout_metrics(self):
        aspect_map = {
            "9:16 (Portrait)": (9, 16),
            "4:5 (Portrait)": (4, 5),
            "1376:1760 (Old)": (1376, 1760),
        }

        target_h = self.force_even(self.res_combo.currentText())
        num = max(len(self.files), 1)
        mode = self.layout_combo.currentText()
        rows = 1 if mode == "Single Row" else math.ceil(num / 2)
        cols_per_row = num if mode == "Single Row" else 2

        tile_h = self.force_even(target_h / rows)
        ar_w, ar_h = aspect_map[self.aspect_combo.currentText()]
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

    def update_resolution_preview(self):
        m = self.get_layout_metrics()
        header_text = f" + {m['header_h']} px header" if m["header_h"] > 0 else ""
        clip_count = len(self.files)
        self.resolution_info_label.setText(
            f"Clips: {clip_count}   |   Final output: {m['canvas_w']}x{m['canvas_h']}   |   "
            f"Each video tile: {m['tile_w']}x{m['tile_h']}{header_text}"
        )

    def process_video(self):
        if not self.files:
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save WebM",
            os.path.join(self.default_dir, "output.webm"),
            "WebM (*.webm)"
        )
        if not save_path:
            return

        self.last_output_dir = os.path.dirname(save_path)
        self.start_btn.setEnabled(False)
        self.log_area.setText("Encoding...")

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

        inputs = ""
        filters = []

        for i, f in enumerate(self.files):
            inputs += f'-hwaccel cuda -i "{f}" '
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

            if count == cols_per_row:
                filters.append(f"{vids}hstack=inputs={count}:shortest=1[r{r}]")
            else:
                full_row_w = tile_w * cols_per_row
                filters.append(f"{vids}pad=w={full_row_w}:h={box_h}:x=(ow-iw)/2:y=0:color=black[r{r}]")
            row_labels.append(f"[r{r}]")

        f_graph = ";".join(filters)
        if len(row_labels) > 1:
            f_graph += f";{''.join(row_labels)}vstack=inputs={len(row_labels)}:shortest=1[outv]"
        else:
            f_graph += f";{row_labels[0]}null[outv]"

        self.last_cmd = (
            f'ffmpeg -y {inputs} -filter_complex "{f_graph}" -map "[outv]" '
            f'-c:v av1_nvenc -preset {self.preset_combo.currentText()} '
            f'-cq {self.cq_spin.value()} -b:v 0 -pix_fmt yuv420p "{save_path}"'
        )

        try:
            result = subprocess.run(self.last_cmd, shell=True, capture_output=True, text=True)
            self.start_btn.setEnabled(True)
            if result.returncode == 0:
                self.log_area.append("\nSUCCESS.")
                self.open_folder_btn.setVisible(True)
                self.copy_btn.setVisible(True)
            else:
                self.log_area.append(f"\nERROR:\n{result.stderr}")
        except Exception as e:
            self.log_area.append(f"\nSystem Error: {str(e)}")
            self.start_btn.setEnabled(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoTool()
    window.show()
    sys.exit(app.exec())
