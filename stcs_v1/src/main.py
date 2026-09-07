# src/main.py
import sys
import os
import logging
from dotenv import load_dotenv

# Load .env file before anything else
load_dotenv()

# Ensure pathing works for both dev and bundled EXE
if getattr(sys, 'frozen', False):
    # PyInstaller temp folder for code/bundled assets
    bundle_root = sys._MEIPASS
    # Folder containing the actual EXE (for external config/data)
    external_root = os.path.dirname(sys.executable)
else:
    # Development mode
    bundle_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    external_root = bundle_root

# Export to environment for global access
os.environ['STCS_BUNDLE_ROOT'] = bundle_root
os.environ['STCS_EXTERNAL_ROOT'] = external_root

if bundle_root not in sys.path:
    sys.path.insert(0, bundle_root)

from PyQt6.QtWidgets import QApplication
from src.ui.main_window import MainWindow
from src.ui.styles import DARK_THEME

def main():
    # Setup Logging
    logging.basicConfig(level=logging.INFO, 
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    app = QApplication(sys.argv)
    
    # Apply Default Theme (Dark)
    app.setStyleSheet(DARK_THEME)

    window = MainWindow()
    window.show()
    
    print("Starting ARIES STCS Application...")
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        import datetime
        with open("crash_log.txt", "w") as f:
            f.write(f"Crash at {datetime.datetime.now()}\n")
            traceback.print_exc(file=f)
        sys.exit(1)
