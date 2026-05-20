import sys
from qtpy.QtWidgets import QApplication
from gui.main_window import MainWindow

def main():
    try:
        app = QApplication(sys.argv)
        
        # Aplicar tema visual premium
        from gui.visual_theme import apply_theme
        apply_theme(app)
        
        window = MainWindow()
        window.show()
        window.raise_()
        window.activateWindow()
        sys.exit(app.exec())
    except Exception as e:
        import traceback
        print("\n" + "="*50)
        print(f"FATAL ERROR DURING STARTUP:\n{e}")
        print("="*50)
        traceback.print_exc()
        input("\nPresiona Enter para cerrar...")

if __name__ == "__main__":
    main()
