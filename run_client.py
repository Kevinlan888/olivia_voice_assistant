"""Top-level entry point for the Olivia voice-assistant client.

Usage:
    python run_client.py

Packaging with PyInstaller:
    pip install pyinstaller
    pyinstaller --onefile run_client.py --name olivia-client
"""

from client.main import main

if __name__ == "__main__":
    main()
