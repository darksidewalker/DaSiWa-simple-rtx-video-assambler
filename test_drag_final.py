#!/usr/bin/env python3
"""Automatischer Test der Drag & Drop Umordnungsfunktionalität."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(__file__))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QMimeData, QPoint
from vid_tool import VideoTool, VideoRow

app = QApplication(sys.argv)
tmpdir = tempfile.mkdtemp()
files = []
for i in range(5):
    fp = os.path.join(tmpdir, f'video_{i}.mp4')
    open(fp, 'w').close()
    files.append(fp)

window = VideoTool()
window.files = list(files)
window.rebuild_list_widgets()

# Test 1: Klick-Selektion
print("Test 1: Klick-Selektion...")
row0 = window.row_widgets[files[0]]
row0.selected.emit()
assert window._selected_idx == 0
assert row0._is_selected
print("  OK - Klick selektiert korrekt")

# Test 2: _do_reorder vorwärts (src < dest)
print("\nTest 2: _do_reorder vorwaerts (Index 0 -> Index 4)...")
orig_files = list(window.files)
row0._do_reorder(files[0], files[4])
expected = [os.path.join(tmpdir, f) for f in ['video_1.mp4', 'video_2.mp4', 'video_3.mp4', 'video_4.mp4', 'video_0.mp4']]
assert window.files == expected, f"Erwartet: {expected}\nTatsaechlich: {window.files}"
print(f"  Vorher: {[os.path.basename(f) for f in orig_files]}")
print(f"  Nachher: {[os.path.basename(f) for f in window.files]}")
print("  OK - Vorwaerts-Reorder korrekt")

# Test 3: _do_reorder rueckwaerts (src > dest)
print("\nTest 3: _do_reorder rueckwaerts (Index 4 -> Index 0)...")
window.files = list(orig_files)
window.rebuild_list_widgets()
row4 = window.row_widgets[files[4]]
row4._do_reorder(files[4], files[0])
expected = [os.path.join(tmpdir, f) for f in ['video_4.mp4', 'video_0.mp4', 'video_1.mp4', 'video_2.mp4', 'video_3.mp4']]
assert window.files == expected, f"Erwartet: {expected}\nTatsaechlich: {window.files}"
print(f"  Vorher: {[os.path.basename(f) for f in orig_files]}")
print(f"  Nachher: {[os.path.basename(f) for f in window.files]}")
print("  OK - Rueckwaerts-Reorder korrekt")

# Test 4: Drag-Start mit Maus-Events
print("\nTest 4: Drag-Start via mouseMoveEvent...")
window.files = list(orig_files)
window.rebuild_list_widgets()
row1 = window.row_widgets[files[1]]
row1._drag_started = False
row1._press_pos = QPoint(100, 100)

event = type('MockEvent', (), {
    'buttons': lambda self: Qt.LeftButton,
    'globalPos': lambda self: QPoint(150, 100),
})()
row1.mouseMoveEvent(event)
print(f"  _drag_started nach Move: {row1._drag_started}")
print("  OK - Drag kann gestartet werden")

# Cleanup
for fp in files:
    os.remove(fp)
os.rmdir(tmpdir)

print("\nAlle Tests bestanden!")
