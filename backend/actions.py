def get_status():
    return {
        "status": "online",
        "cad_connected": False
    }


def create_box(length, width, height):
    if min(length, width, height) <= 0:
        raise ValueError("Dimensions must be positive.")

    # CAD integration will be added here later.
    return {
        "action": "create_box",
        "dimensions": {
            "length": length,
            "width": width,
            "height": height
        },
        "executed": False,
        "message": "Validated. CAD software is not connected yet."
    }


def _check_positive(**values):
    """Raise ValueError unless every value is a finite number greater than 0."""
    for name, value in values.items():
        if not (value > 0 and value != float("inf")):  # NaN fails "value > 0" too
            raise ValueError(f"{name.capitalize()} must be a positive number.")


def create_cylinder(radius, height):
    _check_positive(radius=radius, height=height)

    return {
        "action": "create_cylinder",
        "dimensions": {
            "radius": radius,
            "height": height
        },
        "executed": False,
        "message": "Validated. The FreeCAD panel runs this action."
    }


def create_sphere(radius):
    _check_positive(radius=radius)

    return {
        "action": "create_sphere",
        "dimensions": {
            "radius": radius
        },
        "executed": False,
        "message": "Validated. The FreeCAD panel runs this action."
    }


def list_objects():
    # Nothing to validate. The panel reads the objects from the FreeCAD document.
    return {
        "action": "list_objects",
        "executed": False,
        "message": "The FreeCAD panel runs this action."
    }


MAX_COORDINATE = 1_000_000  # mm, a sanity limit for positions
MAX_NAME_LENGTH = 100


def _check_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("An object name is required.")
    name = name.strip()
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError("The object name is too long.")
    return name


def move_object(name, x, y, z):
    name = _check_name(name)
    for axis, value in (("X", x), ("Y", y), ("Z", z)):
        # Written so NaN is rejected too: any comparison with NaN is False.
        if not (-MAX_COORDINATE <= value <= MAX_COORDINATE):
            raise ValueError(f"{axis} must be a number between -{MAX_COORDINATE} and {MAX_COORDINATE}.")

    return {
        "action": "move_object",
        "name": name,
        "position": {
            "x": x,
            "y": y,
            "z": z
        },
        "executed": False,
        "message": "Validated. The FreeCAD panel runs this action."
    }


def delete_object(name):
    name = _check_name(name)

    return {
        "action": "delete_object",
        "name": name,
        "executed": False,
        "message": "Validated. The FreeCAD panel runs this action."
    }