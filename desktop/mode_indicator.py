"""Compact click-through mode icon with a dwell countdown halo."""
import math
from pathlib import Path

MODE_STYLE = {
    "Click": ("#69dfce", "● CLICK"),
    "Double click": ("#81c8ff", "● DOUBLE CLICK"),
    "Right click": ("#f2a9d5", "● RIGHT CLICK"),
    "Drag": ("#ffbb70", "◆ DRAG"),
    "Page": ("#c7adff", "↕ PAGE"),
    "Scroll": ("#c7adff", "↕ SCROLL"),
}
BADGE_SIZE = (38, 38)  # 26-point preview disc, plus room for the timer and antialiasing.
_view_type = None


def icon_state(mode, *, progress=0, dwell=False, dragging=False, clicked=False, recentering=False):
    if mode not in MODE_STYLE:
        raise ValueError("Unknown pointer mode")
    progress = float(progress)
    progress = max(0, min(1, progress)) if math.isfinite(progress) else 0
    colour = "#a8bdc7" if recentering else MODE_STYLE[mode][0]
    symbol = ("crosshair" if recentering else "move-vertical" if mode in ("Page", "Scroll")
              else "move" if mode == "Drag" and dragging else "hand" if mode == "Drag"
              else "mouse-pointer-click")
    timer = dwell and mode not in ("Page", "Scroll") and not recentering
    return colour, symbol, progress if timer else 0, timer, bool(clicked and not recentering)


def badge_origin(pointer, screen, size=BADGE_SIZE):
    """AppKit coordinates, including screens with negative origins."""
    x, y = pointer
    sx, sy, width, height = screen
    w, h = size
    margin, gap = 6, 12
    left = x + gap if x + gap + w <= sx + width - margin else x - gap - w
    bottom = y - h - gap if y - h - gap >= sy + margin else y + gap
    return (max(sx + margin, min(left, sx + width - w - margin)),
            max(sy + margin, min(bottom, sy + height - h - margin)))


def colour(kit, hex_colour, alpha=1):
    rgb = [int(hex_colour[i:i+2], 16) / 255 for i in (1, 3, 5)]
    return kit.NSColor.colorWithCalibratedRed_green_blue_alpha_(*rgb, alpha)


def at_reveal_edge(pointer, screen, band=4):
    """Leave macOS screen-edge reveal/hot-corner tracking unobstructed."""
    x, y = pointer
    sx, sy, width, height = screen
    return min(x-sx, y-sy, sx+width-x, sy+height-y) <= band


def mode_icon_view(kit):
    global _view_type
    if _view_type is not None:
        return _view_type

    class HeadMouseModeIconView(kit.NSView):
        def isOpaque(self):
            return False

        def drawRect_(self, _rect):
            tint, symbol, progress, timer, clicked = self.indicator_state
            if timer or clicked:
                colour(kit, tint, .24).setStroke()
                track = kit.NSBezierPath.bezierPathWithOvalInRect_(kit.NSMakeRect(2, 2, 34, 34))
                track.setLineWidth_(2)
                track.stroke()
            if progress > 0 or clicked:
                colour(kit, tint).setStroke()
                arc = kit.NSBezierPath.bezierPath()
                arc.setLineWidth_(2.5)
                arc.setLineCapStyle_(kit.NSRoundLineCapStyle)
                arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                    (19, 19), 17, 90, 90-360*(1 if clicked else progress), True)
                arc.stroke()
            colour(kit, tint).setFill()
            kit.NSBezierPath.bezierPathWithOvalInRect_(kit.NSMakeRect(6, 6, 26, 26)).fill()
            image = self.symbols.get(symbol)
            if image:
                image.drawInRect_fromRect_operation_fraction_(kit.NSMakeRect(10.5, 10.5, 17, 17),
                                                               kit.NSZeroRect,
                                                               kit.NSCompositingOperationSourceOver, 1)
            marker = {"Double click": "2", "Right click": "R"}.get(self.action_mode)
            if marker and symbol != "crosshair":
                colour(kit, "#152b35").setFill()
                kit.NSBezierPath.bezierPathWithOvalInRect_(kit.NSMakeRect(23, 22, 12, 12)).fill()
                attributes = {kit.NSFontAttributeName: kit.NSFont.boldSystemFontOfSize_(9),
                              kit.NSForegroundColorAttributeName: kit.NSColor.whiteColor()}
                from Foundation import NSString
                NSString.stringWithString_(marker).drawAtPoint_withAttributes_((26, 22), attributes)


    _view_type = HeadMouseModeIconView
    return _view_type


class MacModeBadge:
    def __init__(self):
        import AppKit as kit
        self.kit = kit
        style = kit.NSWindowStyleMaskBorderless | kit.NSWindowStyleMaskNonactivatingPanel
        self.window = kit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            kit.NSMakeRect(0, 0, *BADGE_SIZE), style, kit.NSBackingStoreBuffered, False)
        self.window.setReleasedWhenClosed_(False)
        self.window.setTitle_("Head Mouse mode icon")
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(kit.NSColor.clearColor())
        self.window.setHasShadow_(False)
        self.window.setIgnoresMouseEvents_(True)
        self.window.setHidesOnDeactivate_(False)
        self.window.setLevel_(kit.NSFloatingWindowLevel)
        self.window.setCollectionBehavior_(kit.NSWindowCollectionBehaviorCanJoinAllSpaces |
                                           kit.NSWindowCollectionBehaviorFullScreenAuxiliary)
        self.view = mode_icon_view(kit).alloc().initWithFrame_(kit.NSMakeRect(0, 0, *BADGE_SIZE))
        self.view.symbols = {}
        folder = Path(__file__).resolve().parent / "assets" / "lucide"
        for symbol in ("mouse-pointer-click", "hand", "move", "move-vertical", "crosshair"):
            image = kit.NSImage.alloc().initWithSize_((17, 17))
            for scale in (1, 2, 3):
                rep = kit.NSBitmapImageRep.imageRepWithContentsOfFile_(str(folder / f"{symbol}@{scale}x.png"))
                if rep is None:
                    raise RuntimeError(f"Mode icon asset missing: {symbol}")
                rep.setSize_((17, 17))
                image.addRepresentation_(rep)
            self.view.symbols[symbol] = image
        self.state = icon_state("Click")
        self.view.action_mode = "Click"
        self.view.indicator_state = self.state
        self.window.setContentView_(self.view)
        self.visible = False

    def show(self, mode, **options):
        kit = self.kit
        self.view.action_mode = mode
        state = icon_state(mode, **options)
        if state != self.state:
            self.state = state
            self.view.indicator_state = state
            self.view.setNeedsDisplay_(True)
        pointer = kit.NSEvent.mouseLocation()
        screens = list(kit.NSScreen.screens())
        screen = next((s for s in screens if kit.NSPointInRect(pointer, s.frame())), None)
        if screen is None:
            self.hide()
            return
        frame = screen.frame()
        if at_reveal_edge((pointer.x, pointer.y), (frame.origin.x, frame.origin.y, frame.size.width, frame.size.height)):
            self.hide()
            return
        origin = badge_origin((pointer.x, pointer.y),
                              (frame.origin.x, frame.origin.y, frame.size.width, frame.size.height))
        self.window.setFrameOrigin_(origin)
        if not self.visible:
            self.window.orderFrontRegardless()
            self.visible = True

    def hide(self):
        if self.visible:
            self.window.orderOut_(None)
            self.visible = False

    def close(self):
        self.hide()
        self.window.close()
