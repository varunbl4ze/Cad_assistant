"""
commands.py - the single menu/toolbar command: open or close the panel.
Importing this module registers the command with FreeCAD.
"""

import os

import FreeCADGui

from cad_assistant import chat_panel

# .../CADAssistant/Resources/cad_assistant.svg  (one folder up from this file)
ICON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Resources", "cad_assistant.svg")


class TogglePanel:
    def GetResources(self):
        return {
            "Pixmap": ICON,
            "MenuText": "Open / Close CAD Assistant",
            "ToolTip": "Show or hide the CAD Assistant sidebar",
        }

    def Activated(self):
        chat_panel.toggle_panel()

    def IsActive(self):
        return True


FreeCADGui.addCommand("CADAssistant_Toggle", TogglePanel())
