"""Selectable application chrome; waveform colors remain user-controlled."""
THEMES = {
    "dark": {"label": "Dark", "bg": "#141d29", "text": "#d8e2ef", "base": "#101720",
             "alternate": "#192331", "button": "#223044", "accent": "#89c8ed", "primary": "#246e94", "muted": "#8fa5bd"},
    "light": {"label": "Light", "bg": "#edf1f5", "text": "#233249", "base": "#ffffff",
              "alternate": "#f2f6fa", "button": "#e3ecf4", "accent": "#155c93", "primary": "#2379b0", "muted": "#556c86"},
    "xp": {"label": "Windows XP風 · Luna", "bg": "#ece9d8", "text": "#182445", "base": "#ffffff",
           "alternate": "#f5f3e8", "button": "#f0eee2", "accent": "#003c74", "primary": "#225ed1", "muted": "#4b5874"},
}


def button_stylesheet():
    colors = {"run": ("#238341", "#339d53"), "stop": ("#bd353b", "#db4d52"),
              "capture": ("#246eae", "#3688cd"), "read": ("#167d86", "#279ca5"),
              "single": ("#a56510", "#bd7b22"), "setup": ("#7751a3", "#9268bf"),
              "local": ("#526981", "#6c839d"), "math": ("#7751a3", "#9268bf"),
              "increase": ("#246eae", "#3688cd"), "decrease": ("#9c641d", "#b87e34")}
    return "\n".join(f'''
        QPushButton[role="{role}"] {{ background: {base}; color: white; border: 1px solid {base}; }}
        QPushButton[role="{role}"]:hover {{ background: {hover}; color: white; }}
        QPushButton[role="{role}"]:pressed {{ background: {base}; border: 2px inset {hover}; }}
        QPushButton[role="{role}"]:disabled {{ background: #78828c; color: #e2e5e8; border-color: #78828c; }}
        ''' for role, (base, hover) in colors.items())


def stylesheet(name):
    t = THEMES[name]
    style = f"""
    QMainWindow, QDialog {{ background: {t['bg']}; color: {t['text']}; }}
    QWidget {{ color: {t['text']}; }}
    QGroupBox {{ border-color: #9da9b8; }}
    QGroupBox::title {{ color: {t['accent']}; }}
    QPushButton, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{ background: {t['button']}; border-color: #9da9b8; }}
    QPushButton:hover {{ background: {t['alternate']}; border-color: {t['accent']}; }}
    QPushButton[accent="true"] {{ background: {t['primary']}; color: white; }}
    QPushButton:disabled {{ color: #888888; background: {t['bg']}; }}
    QTableWidget {{ background: {t['base']}; alternate-background-color: {t['alternate']}; gridline-color: #c4cbd3; border-color: #a4afbd; }}
    QHeaderView::section {{ background: {t['button']}; color: {t['text']}; }}
    QToolBar, QStatusBar {{ background: {t['button']}; }}
    QLabel[muted="true"] {{ color: {t['muted']}; }}
    QTabBar::tab {{ background: {t['button']}; }}
    QTabBar::tab:selected {{ background: {t['primary']}; color: white; }}
    QToolTip {{ background: {t['button']}; color: {t['text']}; border-color: #9da9b8; }}
    """
    if name == "xp":
        style += """
        QWidget { font-family: Tahoma, 'Segoe UI', sans-serif; font-size: 12px; }
        QToolBar { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #4892ff,stop:0.12 #0967f3,stop:0.85 #0050d5,stop:1 #0044bd); border: 1px solid #0855dd; }
        QToolBar QToolButton, QToolBar QLabel, QToolBar QCheckBox { color: white; }
        QToolBar QToolButton:hover { background: #397be6; border: 1px solid #a8ccff; }
        QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #ffffff,stop:0.8 #f2f0e4,stop:1 #dedbc8); border: 1px solid #003c74; border-radius: 3px; }
        QPushButton:hover { border: 2px solid #e6ac3a; }
        QPushButton[accent="true"] { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #4b8ff1,stop:1 #215ac7); color: white; border-color: #003c74; }
        QGroupBox { border: 1px solid #aaa9a0; border-radius: 4px; font-weight: normal; }
        QGroupBox::title { color: #003c74; }
        QLineEdit, QSpinBox, QDoubleSpinBox { background: white; border: 1px solid #7f9db9; border-radius: 0; }
        QHeaderView::section { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #ffffff,stop:1 #e5e3d5); border-right: 1px solid #c6c4b7; }
        """
    return style
