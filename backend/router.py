from actions import get_status, create_box, create_cylinder, create_sphere, list_objects, move_object, delete_object


def execute_command(command: str, parameters: dict):
    if command == "status":
        return get_status()

    if command == "create_box":
        return create_box(
            length=float(parameters.get("length", 0)),
            width=float(parameters.get("width", 0)),
            height=float(parameters.get("height", 0))
        )

    if command == "create_cylinder":
        return create_cylinder(
            radius=float(parameters.get("radius", 0)),
            height=float(parameters.get("height", 0))
        )

    if command == "create_sphere":
        return create_sphere(
            radius=float(parameters.get("radius", 0))
        )

    if command == "list_objects":
        return list_objects()

    if command == "move_object":
        # A missing value becomes None, which float() rejects with a TypeError (HTTP 400).
        return move_object(
            name=parameters.get("name"),
            x=float(parameters.get("x")),
            y=float(parameters.get("y")),
            z=float(parameters.get("z"))
        )

    if command == "delete_object":
        return delete_object(name=parameters.get("name"))

    raise ValueError(f"Unknown command: {command}")