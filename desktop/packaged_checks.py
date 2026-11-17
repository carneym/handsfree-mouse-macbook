"""Read-only release smoke check. Never connects or generates mouse events."""
import importlib
from pathlib import Path
import sys


def run_checks():
    import tkinter as tk
    from preferences import PROFILE_PATH
    from mode_indicator import MacModeBadge, icon_state
    for name in ('serial', 'Quartz', 'CoreBluetooth', 'libdispatch',
                 'bleak.backends.corebluetooth.client',
                 'bleak.backends.corebluetooth.scanner', 'pynput.mouse._darwin'):
        importlib.import_module(name)
    root = tk.Tk()
    root.withdraw()
    root.update_idletasks()
    badge = None
    overlay = None
    try:
        badge = MacModeBadge()
        for mode in ('Click', 'Drag', 'Scroll', 'Double click', 'Right click'):
            badge.view.action_mode = mode
            badge.view.indicator_state = icon_state(mode, dwell=True, progress=.5)
            image = badge.view.bitmapImageRepForCachingDisplayInRect_(badge.view.bounds())
            badge.view.cacheDisplayInRect_toBitmapImageRep_(badge.view.bounds(), image)
            if image is None:
                raise RuntimeError('Mode icon could not be rendered')
        import AppKit as kit
        from types import SimpleNamespace
        from calibration_overlay import CalibrationOverlay
        overlay = CalibrationOverlay(SimpleNamespace(last_rx=None), SimpleNamespace())
        overlay.heading.setStringValue_('Calibrated.')
        overlay.heading.setFrame_(kit.NSMakeRect(50,200,700,100))
        overlay.bar.progress = .5
        rendered = overlay.view.bitmapImageRepForCachingDisplayInRect_(overlay.view.bounds())
        overlay.view.cacheDisplayInRect_toBitmapImageRep_(overlay.view.bounds(), rendered)
        if rendered is None:
            raise RuntimeError('Calibration overlay could not be rendered')
        helper = (Path(sys.executable).resolve().parent.parent /
                  'Helpers/Head Mouse Menu.app/Contents/MacOS/Head Mouse Menu')
        if getattr(sys, 'frozen', False) and not helper.is_file():
            raise RuntimeError('Packaged menu helper is missing')
        return dict(bundled_runtime=bool(getattr(sys, 'frozen', False)),
                    tkinter=str(root.tk.call('info', 'patchlevel')),
                    native_icons='all five rendered', calibration_overlay='rendered', usb_backend='loaded',
                    bluetooth_backend='loaded', mouse_backend='loaded',
                    menu_helper=helper.is_file(), profile_path=str(PROFILE_PATH),
                    pointer_events_posted=0, device_connections_opened=0)
    finally:
        if overlay:
            overlay.close()
        if badge:
            badge.close()
        root.destroy()
