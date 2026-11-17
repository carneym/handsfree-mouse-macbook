"""Standalone entry point for the packaged menu helper (no Tk event loop)."""
import sys

if '--diagnose' in sys.argv:
    from Foundation import NSBundle
    print('Menu bundle:', NSBundle.mainBundle().bundlePath())
    print('Bundled runtime:', bool(getattr(sys, 'frozen', False)))
else:
    from menu_bar import run_child
    run_child()
