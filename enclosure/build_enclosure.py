"""Generate the glasses enclosure in millimetres using manifold3d.

Run with Python 3.10+ after installing requirements-cad.txt.
The STL lid is exported with its broad outer face on the print bed.
"""
from pathlib import Path

import manifold3d as cad
import numpy as np
import trimesh

OUT = Path(__file__).resolve().parent
LENGTH = 54.0
WIDTH = 25.0
WALL = 1.6
FLOOR = 3.6
RIM_Z = 13.8
LID_THICKNESS = 1.6
CORNER_RADIUS = 3.0
LID_CLEARANCE = 0.25
PILOT_DIAMETER = 1.7
SCREW_X = 26.4
SCREW_YS = (4.4, WIDTH - 4.4)
BOSS_RADIUS = 2.5
STRAP_XS = (8.0, 44.0)
STRAP_WIDTH = 4.8
STRAP_HEIGHT = 1.4
BOARD_ORIGIN = (2.2, (WIDTH - 17.8) / 2, 5.7)
BATTERY_ORIGIN = (29.8, (WIDTH - 18.0) / 2, FLOOR + 0.5)


def box(size, origin=(0, 0, 0)):
    return cad.Manifold.cube(size).translate(origin)


def rounded_box(length, width, height, radius, origin=(0, 0, 0)):
    section = cad.CrossSection.square((length - 2 * radius, width - 2 * radius))
    section = section.offset(radius, circular_segments=32).translate((radius, radius))
    return section.extrude(height).translate(origin)


def cylinder(radius, height, origin):
    return cad.Manifold.cylinder(height, radius, radius, 32).translate(origin)


def make_base():
    shell = rounded_box(LENGTH, WIDTH, RIM_Z, CORNER_RADIUS)
    cavity = rounded_box(
        LENGTH - 2 * WALL, WIDTH - 2 * WALL, RIM_Z,
        CORNER_RADIUS - WALL, (WALL, WALL, FLOOR),
    )
    base = shell - cavity

    # Transverse strap tunnels are isolated below the electronics floor.
    for x in STRAP_XS:
        base -= box((STRAP_WIDTH, WIDTH + 2, STRAP_HEIGHT),
                    (x - STRAP_WIDTH / 2, -1, 0.8))

    # Rails touch only narrow board edges. Secure with thin insulating tape.
    for y in (3.3, 20.9):
        base += box((19.5, 0.8, 1.9), (3.0, y, FLOOR))

    # Two central screw towers leave a wire corridor between the bays.
    for y in SCREW_YS:
        base += cylinder(BOSS_RADIUS, RIM_Z - FLOOR, (SCREW_X, y, FLOOR))
        # Join each tower to the adjacent shell wall.
        start_y = WALL - 0.2 if y < WIDTH / 2 else y
        base += box((3.4, 3.0, RIM_Z - FLOOR),
                    (SCREW_X - 1.7, start_y, FLOOR))
        base -= cylinder(PILOT_DIAMETER / 2, 8.0, (SCREW_X, y, RIM_Z - 7.5))

    # Oversized USB plug access for the headerless board at the front.
    base -= box((4.2, 14.0, 7.0), (-1, (WIDTH - 14) / 2, 4.7))
    return base


def make_lid():
    plate = rounded_box(LENGTH, WIDTH, LID_THICKNESS, CORNER_RADIUS,
                        (0, 0, RIM_Z))
    inset = WALL + LID_CLEARANCE
    skirt = rounded_box(
        LENGTH - 2 * inset, WIDTH - 2 * inset, 2.0,
        CORNER_RADIUS - inset, (inset, inset, RIM_Z - 2.0),
    )
    skirt -= rounded_box(
        LENGTH - 2 * (inset + 1.0), WIDTH - 2 * (inset + 1.0), 3.0,
        0.4, (inset + 1.0, inset + 1.0, RIM_Z - 2.5),
    )
    # Leave the rear end open for the full battery length and thickness.
    skirt -= box((4.0, WIDTH + 2, 3.0),
                 (LENGTH - inset - 1.3, -1, RIM_Z - 2.5))
    # The locating skirt clears the screw towers and their wall bridges.
    for y in SCREW_YS:
        skirt -= cylinder(BOSS_RADIUS + LID_CLEARANCE, 3.0, (SCREW_X, y, RIM_Z - 2.5))
        skirt -= box((4.0, 6.0, 3.0),
                     (SCREW_X - 2.0, -1 if y < WIDTH / 2 else WIDTH - 5,
                      RIM_Z - 2.5))
    lid = plate + skirt
    for y in SCREW_YS:
        lid -= cylinder(1.15, 5.0, (SCREW_X, y, RIM_Z - 2.5))
    return lid


def make_coupon():
    coupon = rounded_box(18, WIDTH, FLOOR, CORNER_RADIUS)
    return coupon - box((STRAP_WIDTH, WIDTH + 2, STRAP_HEIGHT),
                        ((18 - STRAP_WIDTH) / 2, -1, 0.8))


def mesh(solid):
    assert solid.status() == cad.Error.NoError, solid.status()
    data = solid.to_mesh()
    return trimesh.Trimesh(np.asarray(data.vert_properties)[:, :3],
                           np.asarray(data.tri_verts), process=True)


def export(solid, name):
    model = mesh(solid)
    assert model.is_watertight, name
    assert model.is_winding_consistent and model.volume > 0, name
    assert len(solid.decompose()) == 1, f"{name} has disconnected parts"
    target = OUT / name
    model.export(target)
    # Check the actual STL round trip, including volume and units.
    loaded = trimesh.load(target, force="mesh")
    assert loaded.is_watertight and loaded.is_winding_consistent
    assert np.allclose(model.extents, loaded.extents, atol=0.001)
    print(f"{name}: {model.extents.round(2)} mm, {model.volume / 1000:.2f} cm³")
    return model


def preview(base, lid, button=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    def render(parts):
        # Orthographic depth buffer avoids hidden triangles showing through
        # concave CAD parts in a painter-style 3D preview.
        width, height = 900, 650
        canvas = np.ones((height, width, 3)) * np.array([.953, .961, .969])
        depth = np.full((height, width), -np.inf)
        eye = np.array([-.9, -1.4, 1.4])
        eye /= np.linalg.norm(eye)
        right = np.cross([0, 0, 1], eye)
        right /= np.linalg.norm(right)
        up = np.cross(eye, right)
        basis = np.array([right, up, eye])
        models = [(mesh(solid), matplotlib.colors.to_rgb(color)) for solid, color in parts]
        all_points = np.concatenate([model.vertices @ basis.T for model, _ in models])
        low, high = all_points[:, :2].min(axis=0), all_points[:, :2].max(axis=0)
        scale = min((width - 60) / (high[0] - low[0]), (height - 50) / (high[1] - low[1]))
        center = (low + high) / 2
        light = np.array([-.4, -.6, 1])
        light /= np.linalg.norm(light)
        for model, color in models:
            projected = model.vertices @ basis.T
            projected[:, 0] = (projected[:, 0] - center[0]) * scale + width / 2
            projected[:, 1] = height / 2 - (projected[:, 1] - center[1]) * scale
            for indices, normal in zip(model.faces, model.face_normals):
                vertices = projected[indices]
                x0, y0 = np.maximum(np.floor(vertices[:, :2].min(axis=0)).astype(int), 0)
                x1, y1 = np.minimum(np.ceil(vertices[:, :2].max(axis=0)).astype(int),
                                   [width - 1, height - 1])
                if x1 < x0 or y1 < y0:
                    continue
                a, b, c = vertices
                divisor = (b[1]-c[1])*(a[0]-c[0]) + (c[0]-b[0])*(a[1]-c[1])
                if abs(divisor) < 1e-9:
                    continue
                yy, xx = np.mgrid[y0:y1+1, x0:x1+1] + .5
                wa = ((b[1]-c[1])*(xx-c[0]) + (c[0]-b[0])*(yy-c[1])) / divisor
                wb = ((c[1]-a[1])*(xx-c[0]) + (a[0]-c[0])*(yy-c[1])) / divisor
                wc = 1 - wa - wb
                z = wa*a[2] + wb*b[2] + wc*c[2]
                region = depth[y0:y1+1, x0:x1+1]
                visible = (wa >= 0) & (wb >= 0) & (wc >= 0) & (z > region)
                region[visible] = z[visible]
                shade = .58 + .42 * max(0, np.dot(normal, light))
                canvas[y0:y1+1, x0:x1+1][visible] = np.array(color) * shade
        return canvas

    blue, lid_blue, green, gold = "#6086a2", "#9fb9cc", "#3f927f", "#dbb66c"
    fig, axes = plt.subplots(1, 2, figsize=(14, 8), facecolor="#f3f5f7")
    title = "Glasses head mouse · recessed button concept" if button is not None else "Glasses head mouse · first fit prototype"
    fig.suptitle(title, x=.045, ha="left",
                 fontsize=23, fontweight="bold", color="#1f3449")
    fig.text(.045, .89, "XIAO nRF52840 Sense + Jauch LP851719JU  ·  all dimensions in mm",
             fontsize=12, color="#455a70")
    exploded = [
        (base, blue), (lid.translate((0, 0, 19)), lid_blue),
        (box((21, 17.8, 1.0), BOARD_ORIGIN).translate((0, 0, 12)), green),
        (box((8, 9, 3), (BOARD_ORIGIN[0], 8, BOARD_ORIGIN[2] + 1)).translate((0, 0, 12)),
         "#aab7c1"),
        (rounded_box(22, 18, 9.2, .8, BATTERY_ORIGIN).translate((0, 0, 12)), gold),
    ]
    assembled = [
        (base, blue), (lid, lid_blue),
        (rounded_box(85, 13, 6, 2, (-15, 6, -8)), "#444c55"),
        (box((50, 18, 1), (2, 3.5, -1)), "#333a40"),
    ]
    if button is not None:
        exploded.append((button.translate((0, 0, 19)), "#dc9258"))
        assembled.append((button, "#dc9258"))
    for x in STRAP_XS:
        loop = box((4, 23, 11.3), (x - 2, 1, -9.2))
        loop -= box((6, 21, 9.3), (x - 3, 2, -8.2))
        assembled.append((loop, "#dc9258"))
    for ax, parts, title in zip(axes, (exploded, assembled),
                               ("Exploded view", "Mounting concept")):
        ax.imshow(render(parts))
        ax.set_axis_off()
        ax.set_title(title, loc="left", fontsize=15, color="#1f3449")
    legend = [
        Patch(color=blue, label="Base · USB access at front"),
        Patch(color=green, label="Headerless board"),
        Patch(color=gold, label="Battery"),
        Patch(color=lid_blue, label="Lid · two M2 screws"),
    ]
    if button is not None:
        legend.append(Patch(color="#dc9258", label="Recessed pause / re-zero button"))
    axes[0].legend(handles=legend, loc="upper left", bbox_to_anchor=(0, -.02),
                   ncol=2, frameon=False, fontsize=10)
    axes[1].text(0, -.06, "54 × 25 × 15.4 body · soft liner · two straps",
                 transform=axes[1].transAxes, fontsize=11, color="#455a70")
    axes[1].text(0, -.13, "Glasses arm shown schematically",
                 transform=axes[1].transAxes, fontsize=10, color="#455a70")
    note = ("Button location and size are provisional. Switch supports and wiring need detailing."
            if button is not None else
            "Print the small strap test piece first. Exact Meta Ray-Ban fit still needs checking.")
    fig.text(.045, .09, note,
             fontsize=12, color="#455a70")
    fig.text(.045, .052, "Electronics shown as clearance envelopes. Prototype has not been physically fitted or printed.",
             fontsize=10, color="#455a70")
    fig.subplots_adjust(left=.035, right=.98, top=.84, bottom=.24, wspace=.08)
    filename = "button_concept.png" if button is not None else "enclosure_preview.png"
    fig.savefig(OUT / filename, dpi=160)
    plt.close(fig)


def main():
    base, lid = make_base(), make_lid()
    assert (base ^ lid).volume() < 0.001, "Lid intersects the base"
    board = box((21, 17.8, 4.5), BOARD_ORIGIN)
    battery = box((22, 18, 9.2), BATTERY_ORIGIN)
    for name, envelope in (("board", board), ("battery", battery)):
        assert (base ^ envelope).volume() < 0.001, f"{name} intersects the base"
        assert (lid ^ envelope).volume() < 0.001, f"{name} intersects the lid"

    export(base, "base.stl")
    # Turn the lid over so the flat top face is on the bed.
    printable_lid = lid.rotate((180, 0, 0)).translate((0, WIDTH, RIM_Z + LID_THICKNESS))
    export(printable_lid, "lid.stl")
    export(make_coupon(), "strap_test.stl")
    preview(base, lid)
    print("Lid fit and electronics envelope checks passed. Physical fitting is required.")


if __name__ == "__main__":
    main()
