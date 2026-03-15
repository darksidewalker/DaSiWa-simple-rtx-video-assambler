# DaSiWa-simple-rtx-video-merger

A specialized tool for creating side-by-side or grid comparisons using NVENC AV1 hardware acceleration.

## 🚀 How to Start
1. Ensure **Python** is installed.
2. Ensure **FFmpeg** is in your Windows Path (so the command `ffmpeg` works in terminal).
3. **Right-click** `setup_and_run.ps1` and select **"Run with PowerShell"**.

## 🛠 How to Use
1. **Add Videos:** Drag and drop your `.webm` or `.mp4` files directly into the list, or use the "Add Manually" button.
2. **Reorder:** Select a file in the list and use "Move Up" or "Move Down" to set the left-to-right/top-to-bottom sequence.
3. **Configure:** - **Height:** Select the total vertical resolution (e.g., 1080).
   - **Layout:** Choose "Single Row" for a wide horizontal strip or "Grid" for a 2-column stack.
   - **Quality (CQ):** 30 is balanced; lower (e.g., 20) is higher quality/larger file.
4. **Encode:** Click "START AV1 ENCODE". It will default to naming the file `output.webm` in your Videos folder.
5. **Finish:** Once done, click "Open Folder" to view your result or "Copy Cmd" to see the exact FFmpeg string used.

## 💡 Notes
- The tool automatically handles 3-video grids by centering the 3rd video on the second row.
- Extension names (like .webm) are automatically stripped from the on-screen overlay.