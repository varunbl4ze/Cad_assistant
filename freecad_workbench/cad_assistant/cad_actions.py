"""
cad_actions.py - runs validated actions inside FreeCAD.

This is the ONLY place that touches the FreeCAD document. It works from a fixed
list of known actions (a "whitelist"). Anything not on the list is refused, and
no Python code is ever executed from a message.

It must be called from FreeCAD's main (UI) thread.
"""

import math
from contextlib import contextmanager

MAX_LISTED = 50          # /list shows at most this many objects
MAX_COORDINATE = 1000000  # mm, same sanity limit as the backend

# The only kinds of object this assistant is allowed to move or delete.
SHAPE_TYPES = ("Part::Box", "Part::Cylinder", "Part::Sphere")


def run_action(action):
    """
    Run one action dict returned by the backend, e.g.
        {"action": "create_box", "dimensions": {"length": 50, "width": 20, "height": 10}}
    Returns a message for the chat. Raises ValueError if something is wrong.
    """
    if not isinstance(action, dict):
        raise ValueError("Backend returned an unexpected result.")

    # The whitelist: action name -> function that runs it.
    actions = {
        "create_box": _create_box,
        "create_cylinder": _create_cylinder,
        "create_sphere": _create_sphere,
        "list_objects": _list_objects,
        "move_object": _move_object,
        "delete_object": _delete_object,
    }
    name = action.get("action")
    if name not in actions:
        raise ValueError("Unsupported action: %s" % name)
    return actions[name](action)


# ---------- helpers ----------

def _positive_numbers(values_dict, keys):
    """Return the named values as floats, or raise ValueError if any is missing or not positive."""
    try:
        values = [float(values_dict[k]) for k in keys]
    except (KeyError, TypeError, ValueError):
        raise ValueError("Backend returned invalid dimensions.")
    if not all(math.isfinite(v) and v > 0 for v in values):
        raise ValueError("Dimensions must be positive numbers.")
    return values


@contextmanager
def _transaction(doc, text):
    """
    Group everything done inside `with _transaction(...):` into ONE undo step.
    If anything fails, the changes are cancelled.
    """
    doc.openTransaction(text)
    try:
        yield
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()


def _fit_view():
    import FreeCADGui
    try:
        FreeCADGui.SendMsgToActiveView("ViewFit")  # zoom so everything is visible
    except Exception:
        pass  # zooming is a nicety; never fail the action because of it


def _find_object(name):
    """
    Find the one shape the person means. Names are the labels shown by /list.
    Raises ValueError (with a helpful message) if there is no match, more than one
    match, or the object is not a shape this assistant may change.
    """
    import FreeCAD

    doc = FreeCAD.ActiveDocument
    if doc is None or not doc.Objects:
        raise ValueError("There are no objects yet. Try: /box 50 20 10")

    matches = [o for o in doc.Objects if o.Label == name]
    if not matches:  # be forgiving about capital letters: "box" finds "Box"
        matches = [o for o in doc.Objects if o.Label.lower() == name.lower()]

    if not matches:
        names = ", ".join(o.Label for o in doc.Objects[:20])
        raise ValueError("No object named '%s'. Objects here: %s" % (name, names))
    if len(matches) > 1:
        raise ValueError("%d objects are named '%s'. Rename them so each name is unique." % (len(matches), name))

    obj = matches[0]
    if obj.TypeId not in SHAPE_TYPES:
        raise ValueError("'%s' is a %s, which this assistant can't change yet." % (obj.Label, obj.TypeId))
    return doc, obj


def _read_position(position):
    """Return None if there is no position, otherwise a checked (x, y, z) tuple."""
    if position is None:
        return None
    try:
        x, y, z = (float(position[k]) for k in ("x", "y", "z"))
    except (KeyError, TypeError, ValueError):
        raise ValueError("Backend returned an invalid position.")
    if not all(math.isfinite(v) and abs(v) <= MAX_COORDINATE for v in (x, y, z)):
        raise ValueError("Position values are out of range.")
    return (x, y, z)


def _at(position):
    """Text for a message: " at (60, 0, 0)", or nothing if the object was left at the origin."""
    return "" if position is None else " at (%g, %g, %g)" % position


def _make_part(type_id, label, properties, undo_text, position=None):
    """
    Create one Part primitive (box, cylinder, ...) inside a transaction and return it.
    `properties` is built by our own code (never from the user), e.g. {"Radius": 10.0}.
    `position` is an optional (x, y, z) in mm; without it the object starts at the origin.
    """
    # Imported here (not at the top) so this file can be read outside FreeCAD.
    import FreeCAD
    import Part  # noqa: F401  (the Part module owns Part::Box and friends)
    import PartGui  # noqa: F401  (without this, a Part object can exist but not be drawn in the 3D view)

    doc = FreeCAD.ActiveDocument or FreeCAD.newDocument("Unnamed")
    with _transaction(doc, undo_text):
        obj = doc.addObject(type_id, label)
        for name, value in properties.items():
            setattr(obj, name, value)  # FreeCAD lengths are in millimetres
        if position is not None:
            obj.Placement = FreeCAD.Placement(FreeCAD.Vector(*position), obj.Placement.Rotation)
        doc.recompute()
    _fit_view()
    return obj


# ---------- the actions ----------

def _create_box(action):
    length, width, height = _positive_numbers(action.get("dimensions", {}), ("length", "width", "height"))
    position = _read_position(action.get("position"))
    box = _make_part(
        "Part::Box", "Box",
        {"Length": length, "Width": width, "Height": height},
        "CAD Assistant: Create Box", position,
    )
    return "Created %s (%g x %g x %g mm)%s. Press Ctrl+Z to undo." % (box.Label, length, width, height, _at(position))


def _create_cylinder(action):
    radius, height = _positive_numbers(action.get("dimensions", {}), ("radius", "height"))
    position = _read_position(action.get("position"))
    cylinder = _make_part(
        "Part::Cylinder", "Cylinder",
        {"Radius": radius, "Height": height},
        "CAD Assistant: Create Cylinder", position,
    )
    return "Created %s (radius %g, height %g mm)%s. Press Ctrl+Z to undo." % (cylinder.Label, radius, height, _at(position))


def _create_sphere(action):
    (radius,) = _positive_numbers(action.get("dimensions", {}), ("radius",))
    position = _read_position(action.get("position"))
    sphere = _make_part(
        "Part::Sphere", "Sphere",
        {"Radius": radius},
        "CAD Assistant: Create Sphere", position,
    )
    return "Created %s (radius %g mm)%s. Press Ctrl+Z to undo." % (sphere.Label, radius, _at(position))


def _move_object(action):
    """Set an object's position (absolute, in mm). Its rotation is kept."""
    position = action.get("position", {})
    try:
        x, y, z = (float(position[k]) for k in ("x", "y", "z"))
    except (KeyError, TypeError, ValueError):
        raise ValueError("Backend returned an invalid position.")
    if not all(math.isfinite(v) and abs(v) <= MAX_COORDINATE for v in (x, y, z)):
        raise ValueError("Position values are out of range.")

    doc, obj = _find_object(str(action.get("name", "")))

    import FreeCAD
    with _transaction(doc, "CAD Assistant: Move %s" % obj.Label):
        obj.Placement = FreeCAD.Placement(FreeCAD.Vector(x, y, z), obj.Placement.Rotation)
        doc.recompute()
    _fit_view()
    return "Moved %s to (%g, %g, %g) mm. Press Ctrl+Z to undo." % (obj.Label, x, y, z)


def _delete_object(action):
    doc, obj = _find_object(str(action.get("name", "")))

    # Never delete something other objects are built from (for example a box inside a Fusion).
    users = [o.Label for o in getattr(obj, "InList", [])]
    if users:
        raise ValueError("%s is used by %s. Delete those first." % (obj.Label, ", ".join(users)))

    label = obj.Label
    with _transaction(doc, "CAD Assistant: Delete %s" % label):
        doc.removeObject(obj.Name)
        doc.recompute()
    _fit_view()
    return "Deleted %s. Press Ctrl+Z to restore it." % label


def _describe(obj):
    """One line about an object: its size for the shapes we can create, and where it is."""
    try:
        if obj.TypeId == "Part::Box":
            size = "%g x %g x %g mm" % (obj.Length.Value, obj.Width.Value, obj.Height.Value)
        elif obj.TypeId == "Part::Cylinder":
            size = "radius %g, height %g mm" % (obj.Radius.Value, obj.Height.Value)
        elif obj.TypeId == "Part::Sphere":
            size = "radius %g mm" % obj.Radius.Value
        else:
            return "%s: %s" % (obj.Label, obj.TypeId)
        base = obj.Placement.Base
        return "%s: %s at (%g, %g, %g)" % (obj.Label, size, base.x, base.y, base.z)
    except Exception:
        return "%s: %s" % (obj.Label, obj.TypeId)  # never fail a listing because of one odd object


def _list_objects(action):
    """Read-only: report what is in the active document. Changes nothing."""
    import FreeCAD

    doc = FreeCAD.ActiveDocument
    if doc is None or not doc.Objects:
        return "There are no objects yet. Try: /box 50 20 10"

    lines = [_describe(obj) for obj in doc.Objects[:MAX_LISTED]]
    extra = len(doc.Objects) - MAX_LISTED
    if extra > 0:
        lines.append("...and %d more" % extra)
    return "Objects in %s (%d):\n%s" % (doc.Label, len(doc.Objects), "\n".join(lines))


# ---------- information for the planner and for the approval card ----------

def get_context():
    """
    A small read-only summary of the active document, sent to the planner so it knows
    what exists. Changes nothing. Returns a list of dicts (empty if nothing is open).
    """
    import FreeCAD

    doc = FreeCAD.ActiveDocument
    if doc is None:
        return []

    context = []
    for obj in doc.Objects[:MAX_LISTED]:
        item = {"label": obj.Label, "type": obj.TypeId}
        try:
            if obj.TypeId == "Part::Box":
                item["size"] = {"length": obj.Length.Value, "width": obj.Width.Value, "height": obj.Height.Value}
            elif obj.TypeId == "Part::Cylinder":
                item["size"] = {"radius": obj.Radius.Value, "height": obj.Height.Value}
            elif obj.TypeId == "Part::Sphere":
                item["size"] = {"radius": obj.Radius.Value}
            if "size" in item:
                base = obj.Placement.Base
                item["position"] = {"x": base.x, "y": base.y, "z": base.z}
        except Exception:
            pass  # a summary is optional; skip details for an odd object
        context.append(item)
    return context


def _g(value):
    return "%g" % float(value)


def describe_step(step):
    """One readable line for a proposed step, shown to the person before they approve."""
    command = step.get("command")
    p = step.get("parameters", {})
    try:
        where = ""
        if any(k in p for k in ("x", "y", "z")):
            where = " at (%s, %s, %s)" % (_g(p.get("x", 0)), _g(p.get("y", 0)), _g(p.get("z", 0)))
        if command == "create_box":
            return "Create a box %s x %s x %s mm%s" % (_g(p["length"]), _g(p["width"]), _g(p["height"]), where)
        if command == "create_cylinder":
            return "Create a cylinder (radius %s, height %s mm)%s" % (_g(p["radius"]), _g(p["height"]), where)
        if command == "create_sphere":
            return "Create a sphere (radius %s mm)%s" % (_g(p["radius"]), where)
        if command == "move_object":
            return "Move %s to (%s, %s, %s) mm" % (p["name"], _g(p["x"]), _g(p["y"]), _g(p["z"]))
        if command == "delete_object":
            return "Delete %s" % p["name"]
    except (KeyError, TypeError, ValueError):
        pass
    return "Run %s" % command