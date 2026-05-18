# run.pyw — Console-free launcher for Windows.
#
# On Windows, Python associates .pyw files with pythonw.exe, which runs
# without opening a console window.  Double-click this file instead of
# main.py to launch the Steno Editor silently.
#
# Usage:
#   Double-click  run.pyw          (Windows Explorer)
#   pythonw       run.pyw          (command line, no console)
#   python        run.pyw          (command line, console visible — same as main.py)

import sys
import os

# Ensure imports resolve from this directory regardless of working directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from main import StenoApp

app = StenoApp()
app.mainloop()
