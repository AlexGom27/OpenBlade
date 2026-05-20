from qtpy.QtWidgets import QApplication
from qtpy.QtGui import QFont, QPalette, QColor
from qtpy.QtCore import Qt

# Colores base del tema (Estética Premium Dark)
COLORS = {
    'background': '#1a1a1f',
    'surface':    '#25252b',
    'surface_alt':'#2d2d35',
    'primary':    '#0e639c',
    'primary_light':'#16825d',
    'accent':     '#e06c75',
    'text':       '#d4d4d4',
    'text_dim':   '#909090',
    'border':     '#3a3a45',
    'success':    '#2e7d32',
    'error':      '#c24040',
    'warning':    '#e2b714',
}

STYLESHEET = f"""
/* ---- Ventana principal y base ---- */
QMainWindow {{
    background-color: {COLORS['background']};
}}

QWidget {{
    background-color: {COLORS['background']};
    color: {COLORS['text']};
    font-family: 'Segoe UI', 'Roboto', 'Helvetica Neue', Arial, sans-serif;
    font-size: 13px;
}}

/* ---- ScrollAreas y vistas ---- */
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: {COLORS['surface']};
    width: 10px;
    margin: 0px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    background: {COLORS['border']};
    min-height: 20px;
    border-radius: 5px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

/* ---- Pestañas ---- */
QTabWidget::pane {{
    border: 1px solid {COLORS['border']};
    background: {COLORS['surface']};
    border-radius: 4px;
}}
QTabBar::tab {{
    background: {COLORS['surface_alt']};
    color: {COLORS['text_dim']};
    padding: 8px 20px;
    margin-right: 2px;
    border: 1px solid {COLORS['border']};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: bold;
    font-size: 12px;
}}
QTabBar::tab:selected {{
    background: {COLORS['primary']};
    color: white;
    border-color: {COLORS['primary']};
}}
QTabBar::tab:hover:!selected {{
    background: #3a3a48;
    color: {COLORS['text']};
}}

/* ---- Botones ---- */
QPushButton {{
    background-color: {COLORS['surface']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    padding: 8px 18px;
    border-radius: 5px;
    font-weight: 600;
    font-size: 12px;
    min-height: 20px;
}}
QPushButton:hover {{
    background-color: {COLORS['surface_alt']};
    border-color: {COLORS['primary']};
}}
QPushButton:pressed {{
    background-color: {COLORS['primary']};
    color: white;
}}
QPushButton:disabled {{
    background-color: {COLORS['surface']};
    color: {COLORS['text_dim']};
    border: 1px solid {COLORS['border']};
}}

/* Botones de acción importante */
QPushButton#runButton {{
    background-color: {COLORS['primary']};
    color: white;
    font-weight: bold;
    border: none;
    padding: 12px 24px;
    font-size: 14px;
    border-radius: 6px;
}}
QPushButton#runButton:hover {{
    background-color: #1177bb;
}}
QPushButton#runButton:pressed {{
    background-color: #0a4f7a;
}}

/* ---- Grupo y Boxes colapsables ---- */
QGroupBox {{
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    margin-top: 12px;
    font-weight: bold;
    font-size: 14px;
    padding-top: 20px;
    background: {COLORS['surface']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 8px;
    color: {COLORS['text']};
}}

QLineEdit, QDoubleSpinBox, QSpinBox {{
    background-color: {COLORS['surface']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 13px;
    selection-background-color: {COLORS['primary']};
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {{
    border-color: {COLORS['primary']};
}}

/* Botones de SpinBox (Aspecto limpio) */
QDoubleSpinBox::up-button, QSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 22px;
    background: {COLORS['surface_alt']};
    border-left: 1px solid {COLORS['border']};
    border-top-right-radius: 4px;
}}
QDoubleSpinBox::down-button, QSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 22px;
    background: {COLORS['surface_alt']};
    border-left: 1px solid {COLORS['border']};
    border-bottom-right-radius: 4px;
}}
QDoubleSpinBox::up-button:hover, QSpinBox::up-button:hover,
QDoubleSpinBox::down-button:hover, QSpinBox::down-button:hover {{
    background: #3a3a45;
}}

QDoubleSpinBox::up-arrow, QSpinBox::up-arrow {{
    image: url(gui/up_arrow.svg);
    width: 14px;
    height: 14px;
}}
QDoubleSpinBox::down-arrow, QSpinBox::down-arrow {{
    image: url(gui/down_arrow.svg);
    width: 14px;
    height: 14px;
}}

QComboBox {{
    background-color: {COLORS['surface']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    padding: 6px 10px;
    border-radius: 4px;
    min-width: 120px;
    font-size: 13px;
}}
QComboBox:hover {{
    border-color: {COLORS['primary']};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid {COLORS['border']};
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
    background: {COLORS['surface_alt']};
}}
QComboBox::drop-down:hover {{
    background: #3a3a45;
}}
QComboBox::down-arrow {{
    image: url(gui/down_arrow.svg);
    width: 14px;
    height: 14px;
}}
QComboBox QAbstractItemView {{
    background: {COLORS['surface']};
    color: {COLORS['text']};
    selection-background-color: {COLORS['primary']};
    border: 1px solid {COLORS['border']};
    outline: none;
}}

/* ---- Slider ---- */
QSlider::groove:horizontal {{
    border: 1px solid {COLORS['border']};
    height: 6px;
    background: {COLORS['surface_alt']};
    margin: 0px;
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {COLORS['primary']};
    border: none;
    width: 14px;
    margin: -4px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{
    background: #1177bb;
}}

/* ---- CheckBox ---- */
QCheckBox {{
    spacing: 8px;
    font-weight: normal;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    background: {COLORS['surface']};
}}
QCheckBox::indicator:checked {{
    background: {COLORS['primary']};
    border-color: {COLORS['primary']};
}}

/* ---- Tooltips ---- */
QToolTip {{
    background: {COLORS['surface']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 11px;
}}

/* ---- QToolButton (Secciones colapsables) ---- */
QToolButton#collapsibleToggle {{
    border: none;
    background-color: {COLORS['surface_alt']};
    color: {COLORS['text']};
    font-weight: bold;
    font-size: 13px;
    padding: 8px 12px;
    text-align: left;
    border-radius: 5px;
}}
QToolButton#collapsibleToggle:hover {{
    background-color: #3a3a48;
}}
QToolButton#collapsibleToggle:checked {{
    border-bottom: 2px solid {COLORS['primary']};
    background-color: {COLORS['surface']};
}}

/* ---- Consola de logs ---- */
QTextEdit {{
    background-color: #121215;
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    padding: 8px;
    font-family: 'Fira Code', 'Courier New', monospace;
    font-size: 12px;
}}

/* ---- Barra de menú ---- */
QMenuBar {{
    background: {COLORS['surface']};
    border-bottom: 1px solid {COLORS['border']};
    padding: 2px;
    font-size: 13px;
}}
QMenuBar::item {{
    padding: 6px 12px;
    border-radius: 4px;
    margin: 2px;
}}
QMenuBar::item:selected {{
    background: {COLORS['primary']};
    color: white;
}}
QMenu {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    padding: 4px;
    border-radius: 6px;
}}
QMenu::item {{
    padding: 6px 30px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: {COLORS['primary']};
    color: white;
}}
"""

def apply_theme(app: QApplication) -> None:
    """Aplica el tema oscuro personalizado a la aplicación."""
    
    # 1. Paleta base
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(COLORS['background']))
    dark_palette.setColor(QPalette.WindowText, QColor(COLORS['text']))
    dark_palette.setColor(QPalette.Base, QColor(COLORS['surface']))
    dark_palette.setColor(QPalette.AlternateBase, QColor(COLORS['surface_alt']))
    dark_palette.setColor(QPalette.Text, QColor(COLORS['text']))
    dark_palette.setColor(QPalette.Button, QColor(COLORS['surface']))
    dark_palette.setColor(QPalette.ButtonText, QColor(COLORS['text']))
    dark_palette.setColor(QPalette.Highlight, QColor(COLORS['primary']))
    dark_palette.setColor(QPalette.HighlightedText, QColor('white'))
    app.setPalette(dark_palette)
    
    # 2. Fuente global
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    # 3. StyleSheet
    app.setStyleSheet(STYLESHEET)
