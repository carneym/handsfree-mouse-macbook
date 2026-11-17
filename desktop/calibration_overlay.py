"""Centred native calibration prompts, owned entirely by the Cocoa helper."""
_types = None


def overlay_types(kit):
    global _types
    if _types is None:
        import objc
        class HeadMouseCalibrationPanel(kit.NSPanel):
            def canBecomeKeyWindow(self):
                return True

            def canBecomeMainWindow(self):
                return False

            def cancelOperation_(self, _sender):
                self.owner.cancel()

            def keyDown_(self, event):
                if event.keyCode() == 53:
                    self.owner.cancel()
                else:
                    objc.super(HeadMouseCalibrationPanel, self).keyDown_(event)

        class HeadMouseCalibrationTarget(kit.NSObject):
            def cancel_(self, _sender):
                self.owner.cancel()

            def retry_(self, _sender):
                self.owner.app.retry_guided()

            def startControl_(self, _sender):
                self.owner.app.start_guided_control()

            def done_(self, _sender):
                self.owner.app.dismiss_guided()
                self.owner.menu.toggle()

        class HeadMouseCalibrationBar(kit.NSView):
            def drawRect_(self, _rect):
                rect = self.bounds()
                kit.NSColor.separatorColor().colorWithAlphaComponent_(.3).setFill()
                kit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, 4, 4).fill()
                if self.progress > 0:
                    kit.NSColor.colorWithSRGBRed_green_blue_alpha_(8/255,126/255,119/255,1).setFill()
                    kit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                        kit.NSMakeRect(0,0,rect.size.width*self.progress,rect.size.height),4,4).fill()
        _types = HeadMouseCalibrationPanel, HeadMouseCalibrationTarget, HeadMouseCalibrationBar
    return _types


class CalibrationOverlay:
    def __init__(self, app, menu):
        import AppKit as kit
        self.kit, self.app, self.menu = kit, app, menu
        Panel, Target, Bar = overlay_types(kit)
        self.window = Panel.alloc().initWithContentRect_styleMask_backing_defer_(
            kit.NSMakeRect(0,0,800,500), kit.NSWindowStyleMaskBorderless,
            kit.NSBackingStoreBuffered,False)
        self.window.owner = self
        self.window.setReleasedWhenClosed_(False)
        self.window.setTitle_('Head Mouse · Guided calibration')
        self.window.setLevel_(kit.NSFloatingWindowLevel)
        self.window.setBackgroundColor_(kit.NSColor.clearColor())
        self.window.setHasShadow_(False)
        self.window.setOpaque_(False)
        self.window.setHidesOnDeactivate_(False)
        self.window.setCollectionBehavior_(kit.NSWindowCollectionBehaviorCanJoinAllSpaces |
                                          kit.NSWindowCollectionBehaviorFullScreenAuxiliary)
        self.view = kit.NSView.alloc().initWithFrame_(kit.NSMakeRect(0,0,800,500))
        self.window.setContentView_(self.view)
        self.target = Target.alloc().init()
        self.target.owner = self
        self.heading = self.label(32,False)
        self.note = self.label(13,True)
        self.step = self.label(12,True)
        self.bar = Bar.alloc().initWithFrame_(kit.NSMakeRect(0,0,260,8))
        self.bar.progress = 0
        self.view.addSubview_(self.bar)
        self.cancel_button = self.button('Cancel · Esc','cancel:')
        self.retry_button = self.button('Retry this step','retry:')
        self.done_button = self.button('Done','done:')
        self.control_button = self.button('Turn on computer control','startControl:')
        self.control_button.setBezelColor_(kit.NSColor.colorWithSRGBRed_green_blue_alpha_(8/255,126/255,119/255,1))
        self.control_button.setContentTintColor_(kit.NSColor.whiteColor())
        self.visible = False
        self.last_state = None

    def label(self, size, secondary):
        k = self.kit
        label = k.NSTextField.wrappingLabelWithString_('')
        label.setAlignment_(k.NSTextAlignmentCenter)
        label.setFont_((k.NSFont.systemFontOfSize_ if secondary else k.NSFont.boldSystemFontOfSize_)(size))
        label.setDrawsBackground_(False)
        if secondary:
            label.setTextColor_(k.NSColor.secondaryLabelColor())
        self.view.addSubview_(label)
        return label

    def button(self, title, action):
        button = self.kit.NSButton.buttonWithTitle_target_action_(title,self.target,action)
        button.setBezelStyle_(self.kit.NSBezelStyleRounded)
        self.view.addSubview_(button)
        return button

    def cancel(self):
        self.app.dismiss_guided()

    def show(self, state):
        k = self.kit
        if not self.visible:
            pointer = k.NSEvent.mouseLocation()
            screen = next((s for s in k.NSScreen.screens() if k.NSPointInRect(pointer,s.frame())),k.NSScreen.mainScreen())
            frame = screen.frame()
            self.window.setFrame_display_(frame,False)
            self.view.setFrameSize_(frame.size)
            w,h = frame.size.width,frame.size.height
            width = min(750,w-80)
            centre = h/2
            self.step.setFrame_(k.NSMakeRect((w-width)/2,centre+108,width,22))
            self.heading.setFrame_(k.NSMakeRect((w-width)/2,centre-4,width,100))
            self.note.setFrame_(k.NSMakeRect((w-width)/2,centre-78,width,60))
            self.bar.setFrame_(k.NSMakeRect((w-260)/2,centre-104,260,8))
            self.cancel_button.setFrame_(k.NSMakeRect((w-150)/2,55,150,30))
            self.retry_button.setFrame_(k.NSMakeRect((w-180)/2,centre-160,180,32))
            self.done_button.setFrame_(k.NSMakeRect(w/2-200,55,130,32))
            self.control_button.setFrame_(k.NSMakeRect(w/2-55,55,255,32))
            self.menu.popover.performClose_(None)
            k.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            self.window.makeKeyAndOrderFront_(None)
            self.visible = True
        self.control_button.setEnabled_(self.app.last_rx is not None)
        self.retry_button.setEnabled_(self.app.last_rx is not None)
        if state == self.last_state:
            return
        self.last_state = dict(state)
        self.heading.setStringValue_(state['title'])
        self.note.setStringValue_(state['note'])
        self.step.setStringValue_(state['step'])
        phase = state['phase']
        self.bar.setHidden_(phase != 'capture')
        self.bar.progress = state['progress']
        self.bar.setNeedsDisplay_(True)
        self.cancel_button.setHidden_(phase == 'done')
        self.done_button.setHidden_(phase != 'done')
        self.control_button.setHidden_(phase != 'done')
        self.control_button.setEnabled_(self.app.last_rx is not None)
        self.retry_button.setHidden_(phase != 'error')
        self.retry_button.setTitle_('Restart calibration' if state['restart'] else 'Retry this step')
        self.retry_button.setEnabled_(self.app.last_rx is not None)

    def hide(self):
        if self.visible:
            self.window.orderOut_(None)
            self.visible = False
            self.last_state = None

    def close(self):
        self.hide()
        self.window.close()
