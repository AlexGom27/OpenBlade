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
        # python3 main.py proyecto.obp abre ese proyecto
        if len(sys.argv) > 1 and sys.argv[1].endswith(".obp"):
            window.load_project_file(sys.argv[1])
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
        try:
            input("\nPresiona Enter para cerrar...")
        except (EOFError, RuntimeError):
            pass  # Sin terminal interactiva (ej. doble clic en el .app)

if __name__ == "__main__":
    main()
