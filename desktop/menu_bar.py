"""Native macOS status item and compact controls, sharing HeadMouse state.

A popover keeps ordinary pointer processing running while controls are open.
A tracking-mode timer also services input inside device/transport popup menus.
"""
import time
from collections import deque

TUNING = (("gain", "Pointer speed", 4, 65),
          ("deadzone", "Ignore tiny movements", .2, 5),
          ("sensitivity", "Computer sensitivity", .5, 3))
_target_type = None


def connection_tab(current, previous, connected, *, opening=False):
    if not connected and (opening or previous is None or previous):
        return "Settings"
    if connected and previous is False:
        return "Controls"
    return current


def calibration_needed(app):
    return bool(app.feed and app.motion is None)


def ready_for_control(app):
    return (app.motion is not None and app.last_rx is not None
            and app.capture is None and not app.recentering
            and not getattr(app, "guided_running", False))


def set_transport(app, transport):
    if transport not in ("USB", "Bluetooth"):
        raise ValueError("Unknown connection type")
    if transport != app.transport.get():
        app.auto_connect = False
        app.transport.set(transport)
        app.select_transport()
        app.save_preferences()


def set_tuning(app, name, value):
    limits = {key: (low, high) for key, _label, low, high in TUNING}
    if name not in limits:
        raise ValueError("Unknown pointer setting")
    low, high = limits[name]
    value = float(value)
    if not low <= value <= high:
        raise ValueError("Pointer setting outside range")
    getattr(app, name).set(round(value, 1))


def target_type(kit):
    global _target_type
    if _target_type is None:
        class HeadMouseMenuTarget(kit.NSObject):
            def invoke_(self, sender):
                self.owner.pending.append(sender)

            def track_(self, _timer):
                self.owner.app.read_state()
                self.owner.process_actions()
                self.owner.sync()
        _target_type = HeadMouseMenuTarget
    return _target_type


class MacMenuBar:
    def __init__(self, app):
        import AppKit as kit
        from Foundation import NSRunLoop, NSTimer, NSRunLoopCommonModes
        self.kit, self.app = kit, app
        self.tab, self.expanded = "Controls", False
        self.previous_connection = None
        self.layout_key = None
        self.next_sync = 0
        self.syncing = False
        self.actions, self.fields = {}, {}
        self.pending = deque()
        self.pumping = False
        self.calibration_overlay = None
        self.target = target_type(kit).alloc().init()
        self.target.owner = self
        self.item = kit.NSStatusBar.systemStatusBar().statusItemWithLength_(kit.NSVariableStatusItemLength)
        button = self.item.button()
        image = kit.NSImage.imageWithSystemSymbolName_accessibilityDescription_("cursorarrow.rays", "Head Mouse")
        if image:
            image.setTemplate_(True)
            button.setImage_(image)
        else:
            button.setTitle_("HM")
        button.setToolTip_("Head Mouse · controls and connection settings")
        button.setAccessibilityLabel_("Head Mouse")
        self.bind(button, lambda _sender: self.toggle())
        self.popover = kit.NSPopover.alloc().init()
        self.popover.setBehavior_(kit.NSPopoverBehaviorTransient)
        self.controller = kit.NSViewController.alloc().init()
        self.popover.setContentViewController_(self.controller)
        self.timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
            .02, self.target, "track:", None, True)
        NSRunLoop.mainRunLoop().addTimer_forMode_(self.timer, NSRunLoopCommonModes)
        NSRunLoop.mainRunLoop().addTimer_forMode_(self.timer, kit.NSEventTrackingRunLoopMode)
        self.build()
        self.sync(force=True)

    def bind(self, control, callback):
        tag = len(self.actions) + 1
        self.actions[tag] = callback
        control.setTag_(tag)
        control.setTarget_(self.target)
        control.setAction_("invoke:")
        return control

    def fail(self, error):
        self.app.pause()
        self.app.notice.set(f"Menu action failed. {error}")

    def process_actions(self):
        while self.pending:
            self.dispatch(self.pending.popleft())

    def dispatch(self, sender):
        if self.syncing:
            return
        try:
            self.actions[sender.tag()](sender)
            self.sync(force=True)
        except Exception as error:
            self.fail(error)

    def toggle(self):
        if self.popover.isShown():
            self.popover.performClose_(None)
        else:
            self.tab = connection_tab(self.tab, self.previous_connection, bool(self.app.feed), opening=True)
            self.sync(force=True)
            self.kit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            button = self.item.button()
            self.popover.showRelativeToRect_ofView_preferredEdge_(button.bounds(), button, self.kit.NSMinYEdge)

    def build(self):
        k = self.kit
        self.actions = {tag: action for tag, action in self.actions.items()
                        if tag == self.item.button().tag()}
        self.fields = {}
        self.height = (684 if self.expanded else 534) if self.tab == "Controls" else 560
        if not hasattr(self, "view"):
            self.view = k.NSView.alloc().initWithFrame_(k.NSMakeRect(0, 0, 360, self.height))
            self.controller.setView_(self.view)
        else:
            for child in list(self.view.subviews()):
                child.removeFromSuperview()
            self.view.setFrameSize_((360, self.height))
        self.popover.setContentSize_((360, self.height))
        self.y = self.height - 18
        self.label("Head Mouse", bold=True)
        self.label("", key="connection", small=True)
        self.segment("tabs", ("Controls", "Settings"), self.tab, self.choose_tab)
        self.gap(5)
        if self.tab == "Controls":
            self.button("", self.app.toggle_computer, key="power")
            self.label("Control set", small=True)
            self.segment("set", ("Mode 1", "Mode 2"), self.app.mode_set.get(), self.choose_set)
            self.label("Action", small=True)
            self.segment("action", self.app.available_modes(), self.app.action_mode.get(), self.app.change_mode)
            self.gap(5)
            self.popup("Click method", ("Dwell", "Sound"), self.app.click_method.get(), self.choose_method, "method")
            if self.app.click_method.get() == "Dwell":
                self.slider("dwell_seconds", "Hold still to click", .5, 3, suffix=" s")
            else:
                self.button("Sound setup / test…", self.sound_setup)
            self.button("▾ Pointer tuning" if self.expanded else "▸ Pointer tuning", self.toggle_tuning)
            if self.expanded:
                for name, title, low, high in TUNING:
                    self.slider(name, title, low, high, suffix="×" if name == "sensitivity" else "")
            self.button("Calibrate…", self.app.start_guided, key="calibrate")
            self.button("Recenter head · 3 s", self.app.start_recenter, key="recenter")
            row_y = self.y + 6
            self.fields["recenter"].setFrame_(k.NSMakeRect(18, row_y, 159, 28))
            self.y += 34
            self.button("Re-zero drift", lambda: self.app.start_capture("zero", preserve_axes=True), key="zero")
            self.fields["zero"].setFrame_(k.NSMakeRect(183, row_y, 159, 28))
        else:
            self.popup("Connection", ("USB", "Bluetooth"), self.app.transport.get(),
                       lambda value: set_transport(self.app, value), "transport")
            self.label("Device", small=True)
            self.device = k.NSPopUpButton.alloc().initWithFrame_pullsDown_(self.rect(28), False)
            self.bind(self.device, lambda sender: self.app.ports.set(sender.titleOfSelectedItem()))
            self.view.addSubview_(self.device)
            self.fields["devices"] = self.device
            self.button("Find device", self.app.refresh_devices, key="scan")
            self.button("Connect", self.app.toggle_connection, key="connect")
            self.gap(8)
            self.checkbox("Mode gestures", "gestures_enabled", self.app.reset_gestures)
            self.checkbox("Mode icon + timer halo", "mode_badge_enabled", self.app.update_mode_indicator)
            self.button("Open calibration & full setup…", self.show_setup)
            self.button("Quit Head Mouse", self.quit)
        self.status = k.NSTextField.wrappingLabelWithString_("")
        self.status.setFrame_(k.NSMakeRect(18, 10, 324, 42))
        self.status.setFont_(k.NSFont.systemFontOfSize_(11))
        self.status.setTextColor_(k.NSColor.secondaryLabelColor())
        self.view.addSubview_(self.status)
        self.layout_key = (self.tab, self.expanded, self.app.mode_set.get(), self.app.click_method.get())

    def rect(self, height):
        self.y -= height
        rect = self.kit.NSMakeRect(18, self.y, 324, height)
        self.y -= 6
        return rect

    def gap(self, value):
        self.y -= value

    def label(self, text, *, key=None, small=False, bold=False):
        k = self.kit
        label = k.NSTextField.labelWithString_(text)
        label.setFrame_(self.rect(16 if small else 21))
        label.setFont_((k.NSFont.boldSystemFontOfSize_ if bold else k.NSFont.systemFontOfSize_)(11 if small else 14))
        if small:
            label.setTextColor_(k.NSColor.secondaryLabelColor())
        self.view.addSubview_(label)
        if key:
            self.fields[key] = label
        return label

    def button(self, title, callback, *, key=None):
        b = self.kit.NSButton.buttonWithTitle_target_action_(title, None, None)
        b.setFrame_(self.rect(28))
        b.setBezelStyle_(self.kit.NSBezelStyleRounded)
        self.bind(b, lambda _sender: callback())
        self.view.addSubview_(b)
        if key:
            self.fields[key] = b
        return b

    def segment(self, key, labels, selected, callback):
        k = self.kit
        control = k.NSSegmentedControl.alloc().initWithFrame_(self.rect(28))
        control.setSelectedSegmentBezelColor_(
            k.NSColor.colorWithSRGBRed_green_blue_alpha_(8/255, 126/255, 119/255, 1))
        control.setSegmentCount_(len(labels))
        for index, title in enumerate(labels):
            control.setLabel_forSegment_(title, index)
            control.setWidth_forSegment_(324 / len(labels), index)
        control.setSelectedSegment_(labels.index(selected))
        self.bind(control, lambda sender: callback(labels[sender.selectedSegment()]))
        self.view.addSubview_(control)
        self.fields[key] = control

    def popup(self, title, values, selected, callback, key):
        self.label(title, small=True)
        control = self.kit.NSPopUpButton.alloc().initWithFrame_pullsDown_(self.rect(28), False)
        control.addItemsWithTitles_(values)
        control.selectItemWithTitle_(selected)
        self.bind(control, lambda sender: callback(sender.titleOfSelectedItem()))
        self.view.addSubview_(control)
        self.fields[key] = control

    def slider(self, name, title, low, high, suffix=""):
        label = self.label("", key=name+"_label", small=True)
        slider = self.kit.NSSlider.alloc().initWithFrame_(self.rect(20))
        slider.setMinValue_(low)
        slider.setMaxValue_(high)
        slider.setContinuous_(True)
        slider.setAccessibilityLabel_(title)
        def changed(sender):
            if name == "dwell_seconds":
                self.app.dwell_seconds.set(round(sender.doubleValue(), 1))
            else:
                set_tuning(self.app, name, sender.doubleValue())
        self.bind(slider, changed)
        self.view.addSubview_(slider)
        self.fields[name] = (slider, label, title, suffix)

    def checkbox(self, title, name, callback):
        control = self.kit.NSButton.checkboxWithTitle_target_action_(title, None, None)
        control.setFrame_(self.rect(24))
        def changed(sender):
            getattr(self.app, name).set(bool(sender.state()))
            callback()
        self.bind(control, changed)
        self.view.addSubview_(control)
        self.fields[name] = control

    def choose_tab(self, title):
        self.tab = title

    def choose_set(self, title):
        self.app.mode_set.set(title)
        self.app.change_mode_set()

    def choose_method(self, title):
        self.app.click_method.set(title)
        self.app.change_click_method()

    def toggle_tuning(self):
        self.expanded = not self.expanded

    def show_setup(self):
        self.popover.performClose_(None)
        self.kit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self.app.show_setup()

    def sound_setup(self):
        self.show_setup()
        self.app.open_sound_setup()

    def quit(self):
        self.popover.performClose_(None)
        self.app.quit()

    def sync(self, force=False):
        now = time.monotonic()
        if not force and now < self.next_sync:
            return
        self.next_sync = now + .1
        self.syncing = True
        try:
            a, f = self.app, self.fields
            connected = bool(a.feed)
            self.tab = connection_tab(self.tab, self.previous_connection, connected)
            self.previous_connection = connected
            key = (self.tab, self.expanded, a.mode_set.get(), a.click_method.get())
            if key != self.layout_key:
                self.build()
                f = self.fields
            f["connection"].setStringValue_(a.connection_status.get())
            f["tabs"].setSelectedSegment_(0 if self.tab == "Controls" else 1)
            self.status.setStringValue_(a.notice.get())
            if self.tab == "Controls":
                active = a.active and not a.practice.get()
                f["power"].setTitle_("Turn off computer control" if active else "Turn on computer control")
                f["power"].setEnabled_(active or ready_for_control(a))
                f["action"].setSelectedSegment_(a.available_modes().index(a.action_mode.get()))
                f["recenter"].setEnabled_(ready_for_control(a))
                f["calibrate"].setEnabled_(a.last_rx is not None and not a.capture and not getattr(a, 'guided_running', False))
                needed = calibration_needed(a)
                f["calibrate"].setBezelColor_(self.kit.NSColor.colorWithSRGBRed_green_blue_alpha_(.92,.48,.08,1) if needed else None)
                f["calibrate"].setContentTintColor_(self.kit.NSColor.whiteColor() if needed else None)
                f["zero"].setEnabled_(a.last_rx is not None and a.right is not None and a.down is not None and not a.capture and not a.recentering and not getattr(a, 'guided_running', False))
                for name in ("dwell_seconds", "gain", "deadzone", "sensitivity"):
                    if name in f:
                        slider, label, title, suffix = f[name]
                        value = getattr(a, name).get()
                        slider.setDoubleValue_(value)
                        label.setStringValue_(f"{title}   {value:.1f}{suffix}")
            else:
                f["transport"].selectItemWithTitle_(a.transport.get())
                values = tuple(a.ports["values"])
                if tuple(f["devices"].itemTitles()) != values:
                    f["devices"].removeAllItems()
                    f["devices"].addItemsWithTitles_(values)
                f["devices"].selectItemWithTitle_(a.ports.get())
                f["devices"].setEnabled_(not a.feed and bool(values))
                f["scan"].setEnabled_(not a.feed and not a.scanning)
                f["scan"].setTitle_("Looking for device…" if a.scanning else "Find device")
                f["connect"].setTitle_("Disconnect" if a.feed else "Connect")
                f["connect"].setEnabled_(bool(a.feed or (a.ports.get() and not a.scanning)))
                for name in ("gestures_enabled", "mode_badge_enabled"):
                    f[name].setState_(int(getattr(a, name).get()))
            state = a.state.get('guided')
            if state:
                if self.calibration_overlay is None:
                    from calibration_overlay import CalibrationOverlay
                    self.calibration_overlay = CalibrationOverlay(a, self)
                self.calibration_overlay.show(state)
            elif self.calibration_overlay:
                self.calibration_overlay.hide()
        finally:
            self.syncing = False

    def close(self):
        if self.calibration_overlay:
            self.calibration_overlay.close()
        self.timer.invalidate()
        self.kit.NSApplication.sharedApplication().stop_(None)
        self.popover.performClose_(None)
        self.kit.NSStatusBar.systemStatusBar().removeStatusItem_(self.item)
        self.target.owner = None


class RemoteValue:
    def __init__(self, app, name):
        self.app, self.name = app, name

    def get(self):
        return self.app.state[self.name]

    def set(self, value):
        self.app.state[self.name] = value
        self.app.send('set_variable', self.name, value)


class RemotePorts:
    def __init__(self, app):
        self.app = app

    def __getitem__(self, key):
        return self.app.state['devices']

    def get(self):
        return self.app.state['device']

    def set(self, value):
        self.app.state['device'] = value
        self.app.send('device', value)


class RemoteApp:
    def __init__(self):
        import queue
        self.incoming = queue.Queue()
        self.state = {}
        self.menu = None
        self.opened = False
        self.ports = RemotePorts(self)

    def send(self, action, *args, **kwargs):
        import json
        print(json.dumps(dict(action=action, args=args, kwargs=kwargs)), flush=True)

    def __getattr__(self, name):
        from menu_bridge import VARIABLES, COMMANDS
        if name in VARIABLES:
            return RemoteValue(self, name)
        if name in COMMANDS or name in ('show_setup', 'quit'):
            return lambda *args, **kwargs: self.send(name, *args, **kwargs)
        if name in ('motion', 'capture', 'right', 'down'):
            return True if self.state.get(name) else None
        if name == 'recentering':
            return self.state.get('recentring')
        if name in self.state:
            return self.state[name]
        raise AttributeError(name)

    def available_modes(self):
        return {'Mode 1': ('Click', 'Drag', 'Scroll'),
                'Mode 2': ('Click', 'Double click', 'Right click')}[self.state['mode_set']]

    def read_state(self):
        import queue
        latest = None
        while True:
            try:
                latest = self.incoming.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            self.state.update(latest['state'])


def run_child():
    import json
    import sys
    import threading
    import AppKit as kit
    from Foundation import NSRunLoop, NSTimer, NSRunLoopCommonModes
    app = RemoteApp()
    def read():
        for line in sys.stdin:
            try:
                app.incoming.put(json.loads(line))
            except ValueError:
                pass
        # Parent exited: remove the status item by terminating the helper.
        import os
        os._exit(0)
    threading.Thread(target=read, daemon=True).start()
    native = kit.NSApplication.sharedApplication()
    native.setActivationPolicy_(kit.NSApplicationActivationPolicyAccessory)
    class HeadMouseMenuBootstrap(kit.NSObject):
        def tick_(self, timer):
            if app.menu is None:
                app.read_state()
                if app.state:
                    app.menu = MacMenuBar(app)
                    app.menu.toggle()
                    timer.invalidate()
    bootstrap = HeadMouseMenuBootstrap.alloc().init()
    timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(.02, bootstrap, 'tick:', None, True)
    NSRunLoop.mainRunLoop().addTimer_forMode_(timer, NSRunLoopCommonModes)
    native.run()


if __name__ == '__main__':
    run_child()
