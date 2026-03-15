import sys
import os
import subprocess
import math
from pathlib import Path
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QListWidget, QComboBox,
                             QLabel, QFileDialog, QTextEdit, QSpinBox)
from PySide6.QtGui import QDesktopServices, QClipboard
from PySide6.QtCore import QUrl, Qt

class VideoTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DaSiWa Simple RTX Video Merger")
        self.resize(900, 750)
        self.setAcceptDrops(True)
        self.files = []
        self.last_cmd = ""
        self.default_dir = str(Path.home() / "Videos")
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        layout.addWidget(QLabel("Videos (Drag & Drop here, then reorder):"))
        list_hbox = QHBoxLayout()
        self.file_list = QListWidget()
        list_hbox.addWidget(self.file_list)

        reorder_vbox = QVBoxLayout()
        self.up_btn = QPushButton("Move Up")
        self.down_btn = QPushButton("Move Down")
        self.up_btn.clicked.connect(lambda: self.reorder_item(-1))
        self.down_btn.clicked.connect(lambda: self.reorder_item(1))
        reorder_vbox.addWidget(self.up_btn)
        reorder_vbox.addWidget(self.down_btn)
        reorder_vbox.addStretch()
        list_hbox.addLayout(reorder_vbox)
        layout.addLayout(list_hbox)

        btn_frame = QHBoxLayout()
        self.add_btn = QPushButton("Add Manually")
        self.add_btn.clicked.connect(self.add_files)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_files)
        btn_frame.addWidget(self.add_btn)
        btn_frame.addWidget(self.clear_btn)
        layout.addLayout(btn_frame)

        # Settings
        settings_grid = QVBoxLayout()
        row1 = QHBoxLayout()
        self.res_combo = QComboBox()
        self.res_combo.addItems(["720", "1080", "1440", "2160"])
        self.res_combo.setCurrentText("1080")
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["Grid (Max 2 Cols)", "Single Row"])
        row1.addWidget(QLabel("Height:"))
        row1.addWidget(self.res_combo)
        row1.addWidget(QLabel("Layout:"))
        row1.addWidget(self.layout_combo)
        settings_grid.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Quality (CQ):"))
        self.cq_spin = QSpinBox()
        self.cq_spin.setRange(1, 51)
        self.cq_spin.setValue(30)
        row2.addWidget(self.cq_spin)
        row2.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["p1", "p2", "p3", "p4", "p5", "p6", "p7"])
        self.preset_combo.setCurrentText("p4")
        row2.addWidget(self.preset_combo)
        settings_grid.addLayout(row2)
        layout.addLayout(settings_grid)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("background-color: #0a0a0a; color: #00ff41; font-family: 'Courier New';")
        layout.addWidget(self.log_area)

        self.start_btn = QPushButton("START AV1 ENCODE")
        self.start_btn.setStyleSheet("background-color: #76b900; color: black; font-weight: bold; height: 45px;")
        self.start_btn.clicked.connect(self.process_video)
        layout.addWidget(self.start_btn)

        action_hbox = QHBoxLayout()
        self.open_folder_btn = QPushButton("Open Output Folder")
        self.open_folder_btn.setVisible(False)
        self.open_folder_btn.clicked.connect(self.open_output_folder)

        self.copy_btn = QPushButton("Copy Last Command")
        self.copy_btn.setVisible(False)
        self.copy_btn.clicked.connect(self.copy_command)

        action_hbox.addWidget(self.open_folder_btn)
        action_hbox.addWidget(self.copy_btn)
        layout.addLayout(action_hbox)

        self.last_output_dir = self.default_dir

    def reorder_item(self, direction):
        curr_row = self.file_list.currentRow()
        if curr_row == -1: return
        new_row = curr_row + direction
        if 0 <= new_row < self.file_list.count():
            file = self.files.pop(curr_row)
            self.files.insert(new_row, file)
            item = self.file_list.takeItem(curr_row)
            self.file_list.insertItem(new_row, item)
            self.file_list.setCurrentRow(new_row)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.accept()
        else: event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            f = url.toLocalFile()
            if f.lower().endswith(('.mp4', '.mkv', '.mov', '.avi', '.webm')) and f not in self.files:
                self.files.append(f)
                self.file_list.addItem(os.path.basename(f))

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select Videos", self.default_dir, "Videos (*.mp4 *.mkv *.mov *.avi *.webm)")
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
        self.log_area.append("\nCommand copied to clipboard!")

    def process_video(self):
        if not self.files: return

        # --- Pre-set filename to output.webm ---
        default_save_path = os.path.join(self.default_dir, "output.webm")
        save_path, _ = QFileDialog.getSaveFileName(self, "Save WebM", default_save_path, "WebM (*.webm)")
        if not save_path: return

        self.last_output_dir = os.path.dirname(save_path)
        self.start_btn.setEnabled(False)
        self.log_area.setText("Encoding started...")

        def force_even(n):
            return int(n) if int(n) % 2 == 0 else int(n) - 1

        target_h = force_even(self.res_combo.currentText())
        num = len(self.files)
        mode = self.layout_combo.currentText()
        rows = 1 if mode == "Single Row" else math.ceil(num / 2)
        cols_per_row = num if mode == "Single Row" else 2
        scaled_h = force_even(target_h / rows)

        inputs, filters = "", []
        for i, f in enumerate(self.files):
            inputs += f"-hwaccel cuda -i \"{f}\" "
            fname = os.path.splitext(os.path.basename(f))[0]
            f_size = max(18, scaled_h // 22)
            filters.append(f"[{i}:v]scale=-2:{scaled_h},drawtext=text='{fname}':fontcolor=white:fontsize={f_size}:box=1:boxcolor=black@0.6:x=12:y=12[v{i}]")

        row_outputs = []
        for r in range(rows):
            start, end = r * cols_per_row, min((r+1) * cols_per_row, num)
            vids = "".join([f"[v{i}]" for i in range(start, end)])
            if (end - start) > 1:
                filters.append(f"{vids}hstack=inputs={end-start}:shortest=1[row{r}]")
                row_outputs.append(f"[row{r}]")
            else:
                row_outputs.append(f"[v{start}]")

        f_graph = ";".join(filters)
        if len(row_outputs) > 1:
            all_rows = "".join(row_outputs)
            f_graph += f";{all_rows}vstack=inputs={len(row_outputs)}:shortest=1[outv]"
        else:
            f_graph += f";{row_outputs[0]}null[outv]"

        self.last_cmd = f'ffmpeg -y {inputs} -filter_complex "{f_graph}" -map "[outv]" -c:v av1_nvenc -preset {self.preset_combo.currentText()} -cq {self.cq_spin.value()} -b:v 0 -pix_fmt yuv420p "{save_path}"'

        try:
            result = subprocess.run(self.last_cmd, shell=True, capture_output=True, text=True)
            self.start_btn.setEnabled(True)
            if result.returncode == 0:
                self.log_area.append("\nSUCCESS: Video created.")
                self.open_folder_btn.setVisible(True)
                self.copy_btn.setVisible(True)
            else:
                self.log_area.append(f"\nERROR:\n{result.stderr}")
                self.copy_btn.setVisible(True) # Still show so you can debug
        except Exception as e:
            self.log_area.append(f"\nSystem Error: {str(e)}")
            self.start_btn.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoTool()
    window.show()
    sys.exit(app.exec())
