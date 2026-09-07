# src/ui/styles.py

DARK_THEME = """
    QMainWindow { background-color: #121212; color: #dddddd; }
    QWidget { font-family: 'Segoe UI', sans-serif; }
    QLabel, QPushButton, QLineEdit, QComboBox, QGroupBox, QStatusBar, QCheckBox, QRadioButton, QTabWidget { font-size: 13px; }
    QLabel { color: #dddddd; }
    
    /* Group Box */
    QGroupBox { 
        border: 1px solid #333; 
        margin-top: 20px; 
        font-weight: bold; 
        color: #aaa; 
        background-color: #1e1e1e; 
    }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
    
    /* Buttons */
    QPushButton { border-radius: 4px; padding: 4px 8px; background-color: #333; color: #ddd; border: 1px solid #444; }
    QPushButton:hover { background-color: #444; }
    QPushButton:pressed { background-color: #222; }
    
    /* Inputs */
    QLineEdit { background-color: #222; color: #ddd; border: 1px solid #444; padding: 4px; border-radius: 4px; }
    QComboBox { background-color: #222; color: #ddd; border: 1px solid #444; padding: 4px; border-radius: 4px; }
    QComboBox::drop-down { border: 0px; }
    
    /* Tabs */
    QTabWidget::pane { border: 1px solid #333; }
    QTabBar::tab { background: #222; color: #888; padding: 8px 20px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
    QTabBar::tab:selected { background: #333; color: #ddd; font-weight: bold; }
    
    /* Status Bar */
    QStatusBar { color: #888; background-color: #121212; border-top: 1px solid #333; }

    /* Custom IDs */
    #HeaderTimeLabel { font-family: 'Consolas', monospace; color: #4488ff; font-size: 14px; margin-left: 20px; }
    #RawLabel { font-family: 'Consolas', monospace; font-size: 14px; color: #888888; border: 1px solid #333; padding: 4px; background: #080808; }
"""

LIGHT_THEME = """
    QMainWindow { background-color: #f0f2f5; color: #1c1e21; }
    QWidget { font-family: 'Segoe UI', sans-serif; }
    QLabel, QPushButton, QLineEdit, QComboBox, QGroupBox, QStatusBar, QCheckBox, QRadioButton, QTabWidget { font-size: 13px; }
    QLabel { color: #1c1e21; }
    
    /* Group Box */
    QGroupBox { 
        border: 1px solid #ccc; 
        margin-top: 20px; 
        font-weight: bold; 
        color: #333; 
        background-color: #ffffff; 
    }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
    
    /* Buttons */
    QPushButton { border-radius: 4px; padding: 4px 8px; background-color: #e4e6eb; color: #050505; border: 1px solid #ccc; }
    QPushButton:hover { background-color: #d8dadf; }
    QPushButton:pressed { background-color: #ced0d4; }
    
    /* Inputs */
    QLineEdit { background-color: #ffffff; color: #000; border: 1px solid #ccc; padding: 4px; border-radius: 4px; }
    QComboBox { background-color: #ffffff; color: #000; border: 1px solid #ccc; padding: 4px; border-radius: 4px; }
    QComboBox::drop-down { border: 0px; }
    
    /* Tabs */
    QTabWidget::pane { border: 1px solid #ccc; }
    QTabBar::tab { background: #e4e6eb; color: #606770; padding: 8px 20px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
    QTabBar::tab:selected { background: #ffffff; color: #1877f2; font-weight: bold; border: 1px solid #ccc; border-bottom: none; }
    
    /* Status Bar */
    QStatusBar { color: #333; background-color: #e0e0e0; border-top: 1px solid #ccc; }

    /* Custom IDs */
    #HeaderTimeLabel { font-family: 'Consolas', monospace; color: #0055aa; font-size: 14px; margin-left: 20px; }
    #RawLabel { font-family: 'Consolas', monospace; font-size: 14px; color: #333333; border: 1px solid #ccc; padding: 4px; background: #e4e6eb; }
"""