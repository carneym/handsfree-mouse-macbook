"""macOS pointer events with real relative deltas for screen-edge interactions."""
import time


def constrain_to_displays(target, displays):
    """Keep event locations on a display, including its final visible pixel.

    WindowServer can clamp the visible cursor without clamping the event used
    for hit testing. Posting an off-screen location misses edge UI such as Dock.
    Pick the nearest display when a movement crosses an outside edge or gap.
    """
    x, y = target
    candidates = [(max(left, min(x, left + width - 1)),
                   max(top, min(y, top + height - 1)))
                  for left, top, width, height in displays]
    return min(candidates, key=lambda p: (p[0]-x)**2 + (p[1]-y)**2) if candidates else target


def post_motion(quartz, source, previous, target, drag_button=None, displays=()):
    try:
        (_, _, kind), button = drag_button.value
    except AttributeError:
        kind, button = quartz.kCGEventMouseMoved, 0
    location = constrain_to_displays(target, displays)
    event = quartz.CGEventCreateMouseEvent(source, kind, location, button)
    # Absolute positioning alone leaves these fields zero. Dock reveal can
    # depend on a continued push against the edge even when location clamps.
    for field, delta in ((quartz.kCGMouseEventDeltaX, target[0]-previous[0]),
                         (quartz.kCGMouseEventDeltaY, target[1]-previous[1])):
        quartz.CGEventSetIntegerValueField(event, field, round(delta))
    quartz.CGEventPost(quartz.kCGHIDEventTap, event)


def create_controller():
    import Quartz
    from pynput.mouse import Controller

    class MacPointer(Controller):
        def __init__(self):
            super().__init__()
            self._head_mouse_source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
            self._display_bounds = ()
            self._display_refresh_at = 0

        def _position_get(self):
            # Quartz's own coordinate space avoids mixing display pixels with
            # AppKit points on Retina and differently positioned displays.
            point = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
            return point.x, point.y

        def _position_set(self, target):
            now = time.monotonic()
            if now >= self._display_refresh_at:
                error, display_ids, _count = Quartz.CGGetActiveDisplayList(32, None, None)
                if error:
                    raise RuntimeError(f"Cannot read display bounds ({error})")
                bounds = [Quartz.CGDisplayBounds(display_id) for display_id in display_ids]
                self._display_bounds = [(r.origin.x, r.origin.y, r.size.width, r.size.height)
                                        for r in bounds]
                self._display_refresh_at = now + 1
            post_motion(Quartz, self._head_mouse_source, self._position_get(), target,
                        self._drag_button, self._display_bounds)

    return MacPointer()
