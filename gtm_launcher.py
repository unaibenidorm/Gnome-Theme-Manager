import runpy
from pathlib import Path

def main():
    root = Path(__file__).resolve().parent
    script = root / "gnome-theme-manager.py"
    runpy.run_path(str(script), run_name="__main__")

if __name__ == "__main__":
    main()
