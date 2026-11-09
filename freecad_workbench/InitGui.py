"""
InitGui.py - FreeCAD runs this file at startup and uses it to register the
"CAD Assistant" entry in the Workbench selector.

NOTE: FreeCAD runs this file in a way that hides top-level variables from
inside the class below. So imports happen inside the class and its methods
rather than at the top of the file.
"""

import FreeCADGui


class CADAssistantWorkbench(FreeCADGui.Workbench):
    import FreeCAD

    MenuText = "CAD Assistant"
    ToolTip = "Chat sidebar for the CAD Assistant"
    # FreeCAD 1.x wants a path to an icon file, not inline image data.
    Icon = FreeCAD.getUserAppDataDir() + "Mod/CADAssistant/Resources/cad_assistant.svg"

    def Initialize(self):
        # Runs once, the first time the workbench is selected.
        from cad_assistant import commands  # noqa: F401  (importing registers the command)

        self.appendToolbar("CAD Assistant", ["CADAssistant_Toggle"])
        self.appendMenu("CAD Assistant", ["CADAssistant_Toggle"])

    def Activated(self):
        # Runs every time the user switches to this workbench: show the sidebar.
        from cad_assistant import chat_panel
        chat_panel.show_panel()

    def Deactivated(self):
        pass  # the panel stays open when switching workbenches; close it with the X

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(CADAssistantWorkbench())