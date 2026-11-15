# CAD Assistant for FreeCAD

A chat sidebar inside **FreeCAD** that lets you create simple 3D shapes by typing commands or by describing what you want in plain English. The plain-English mode is powered by a **local AI model running on your own computer** through [Ollama](https://ollama.com), so it needs no account, no API key and no internet connection once set up.

> ## ⚠️ Prototype, not a finished product
> This is an **early prototype** that can do **basic tasks only**. It can create boxes, cylinders and spheres, move them, delete them and list what is in the document. It **cannot** sketch, extrude, rotate, resize, fillet, cut, join or build real parametric parts. The local AI model is small and **will make mistakes**, so every plan is shown to you and nothing changes until you press **Approve**. Expect rough edges and bugs. It is not a replacement for a CAD designer or for professional CAD software.

## What it does

- Adds a **CAD Assistant** workbench to FreeCAD with a dockable, resizable chat sidebar (the normal 3D view stays visible).
- **Typed commands** such as `/box 50 20 10` work without any AI.
- **Plain English** such as *"make a 40 mm cube and put a sphere of radius 20 next to it"* is turned into a plan by a local AI model. You review the plan, then approve or cancel it.
- Remembers the recent conversation and sees what is currently in your document, so follow-ups like *"make the sphere bigger"* can work (results depend on the model).

## Requirements

| Requirement | Notes |
|---|---|
| **FreeCAD** | Developed and tested on **FreeCAD 1.1.4 on Windows**. Other versions and operating systems are untested. This only works inside FreeCAD. |
| **Ollama** | Needed for the plain-English mode. Download from [ollama.com](https://ollama.com). |
| **The `qwen2.5-coder` model** | Needed for the plain-English mode (the author used the 7B size). Install it with `ollama pull qwen2.5-coder:7b`. |
| **Python 3 with `fastapi` and `uvicorn`** | For the backend. Developed with a conda environment on Python 3.14. This is separate from FreeCAD's own Python. |
| **Hardware** | Developed on a PC with 16 GB RAM and an RTX 4050 (6 GB VRAM). A 7B model is slow without a graphics card. |

Typed `/commands` work **without** Ollama or the model. Only the plain-English mode needs them.

## How it works

```
FreeCAD (chat sidebar)  <->  Backend (FastAPI)  <->  Ollama (local AI model)
   freecad_workbench/        backend/                 qwen2.5-coder
```

1. You type a message. The sidebar sends it to the backend, together with a short summary of the objects in your document.
2. The backend asks the AI model for a plan. The model's answer is forced into a fixed JSON format.
3. The backend checks every proposed step with the same rules as typed commands. If any step is invalid, the whole plan is rejected.
4. The plan appears in the chat. **Nothing has changed in FreeCAD yet.**
5. You press **Approve**. Each step is validated again by the backend and then run in FreeCAD.

Safety design:
- The AI can only choose from a short fixed list of actions (create box, cylinder, sphere; move; delete). It **never runs code**.
- Every step is validated twice and needs your approval.
- Everything runs on your computer. Your messages are not sent to the internet.

## Installation

### 1. Install the tools
1. Install [FreeCAD](https://www.freecad.org/downloads.php).
2. Install [Ollama](https://ollama.com), then pull the model:
   ```
   ollama pull qwen2.5-coder:7b
   ```

### 2. Set up the backend
Create a Python environment (conda shown, any works) and install the packages:
```
conda create -n cad-assistant python
conda activate cad-assistant
pip install fastapi uvicorn
```

### 3. Install the FreeCAD workbench
1. Start FreeCAD and open **View > Panels > Python console**. Run:
   ```python
   FreeCAD.getUserAppDataDir() + "Mod"
   ```
   This prints your `Mod` folder, for example `C:\Users\<you>\AppData\Roaming\FreeCAD\v1-1\Mod`. Create it if it does not exist.
2. Close FreeCAD.
3. Copy the **contents** of this repository's `freecad_workbench` folder into a new folder named `CADAssistant` inside `Mod`, so you end up with:
   ```
   Mod\CADAssistant\
   ├── Init.py
   ├── InitGui.py
   ├── Resources\cad_assistant.svg
   └── cad_assistant\
       ├── __init__.py
       ├── backend_client.py
       ├── cad_actions.py
       ├── chat_panel.py
       └── commands.py
   ```
   `Init.py` and `InitGui.py` must sit directly inside `CADAssistant`.
4. Start FreeCAD again.

## Running it

1. Make sure **Ollama is running** (on Windows it lives in the system tray).
2. Start the backend from the `backend` folder:
   ```
   conda activate cad-assistant
   cd backend
   uvicorn main:app --reload
   ```
   Leave this window open. Check it at <http://127.0.0.1:8000/docs>; you should see `POST /plan` listed.
3. Start FreeCAD and choose **CAD Assistant** from the workbench dropdown. The sidebar opens on the right.
4. The status line under the title should say **Backend connected**.

If **CAD Assistant** is missing from the dropdown, check **Edit > Preferences > General > Workbenches** and enable it.

## Using it

**Plain English** (needs Ollama): describe what you want, review the proposed plan, then press **Approve** or **Cancel**.
```
make a 40 mm cube and put a sphere of radius 20 next to it
make the sphere bigger
what can you do?
```

**Typed commands** (no AI needed). Sizes are in millimetres.

| Command | What it does |
|---|---|
| `/box <length> <width> <height>` | Create a box |
| `/cylinder <radius> <height>` | Create a cylinder |
| `/sphere <radius>` | Create a sphere |
| `/list` | List the objects in the active document |
| `/move <name> <x> <y> <z>` | Move an object to an absolute position |
| `/delete <name>` | Delete an object |
| `/url [address]` | Show or change the backend URL |
| `/help` | Show help |

Positions: a box's position is its corner, a cylinder's is the centre of its bottom face, and a sphere's is its centre. Commands create shapes at the origin; plain-English plans may place them elsewhere. Each created object is one undo step, so press Ctrl+Z to undo.

## Configuration

Set these in the terminal **before** starting `uvicorn` (PowerShell shown). All are optional.

| Setting | Purpose | Default |
|---|---|---|
| `CAD_PLANNER` | `ollama` (AI) or `standin` (a few fixed phrases, no AI, for testing) | `ollama` |
| `CAD_OLLAMA_MODEL` | Which Ollama model to use | found automatically (prefers `qwen2.5-coder`) |
| `CAD_OLLAMA_URL` | Where Ollama is listening | `http://127.0.0.1:11434` |
| `CAD_PLANNER_DEBUG` | Set to `1` to print the model's raw answers in the backend window | off |

```
$env:CAD_PLANNER_DEBUG="1"
$env:CAD_OLLAMA_MODEL="qwen2.5-coder:7b"
uvicorn main:app --reload
```

The backend address used by the sidebar defaults to `http://127.0.0.1:8000` and can be changed with `/url`.

**Security note:** the backend has no login. Do not start it with `--host 0.0.0.0` or expose it to a network.

## Known limitations

- Only **box, cylinder, sphere, move, delete and list**. No rotate, resize, boolean operations, fillets, sketches, holes, patterns or assemblies.
- The local model is small. It can misread requests, get positions wrong or invent object names. Always read the plan before approving.
- Plans of several steps need one Ctrl+Z per step to undo.
- The first AI request is slow while Ollama loads the model.
- Tested on one setup only (Windows, FreeCAD 1.1.4). Mac and Linux are untested.
- Large automated test coverage exists only against simulated FreeCAD; real-world bugs are likely.

## Troubleshooting

| Problem | Likely cause and fix |
|---|---|
| Chat says **Not Found** or "no /plan endpoint" | The backend is running an older `main.py`. Update it and restart `uvicorn` from the `backend` folder. |
| **Cannot reach backend** | `uvicorn` is not running, or it uses a different address. Use `/url` to check. |
| **Cannot reach Ollama** | Start Ollama (tray app, or `ollama serve`). |
| **No suitable model found** | Run `ollama pull qwen2.5-coder:7b`, or set `CAD_OLLAMA_MODEL`. |
| Replies say "Try phrases like..." | The built-in fixed-phrase planner is active. Remove the `CAD_PLANNER` setting and restart `uvicorn`. |
| Workbench missing after restart | Check the folder layout above, and look in **View > Panels > Report view** for red errors mentioning `CADAssistant`. |

## Project layout

```
backend/            FastAPI backend: main.py, router.py, actions.py, planner.py
freecad_workbench/  The FreeCAD workbench (copy into FreeCAD's Mod folder)
desktop.py          The original standalone desktop interface (not used by the workbench)
```

## Ideas for the future

These are possibilities, not promises: more actions (rotate, resize, copy, boolean cut and fuse, holes, patterns), sketch and extrude features, grouping a plan into one undo step, and an option to use a stronger hosted AI model instead of a local one.

## Development note

Much of this code was written with the help of an AI coding assistant. Review it before relying on it.

## License

MIT. See [LICENSE](LICENSE). This repository does not include any AI model files. The Qwen models and Ollama have their own licenses, which you should check before redistributing anything.

## Disclaimer

This project is independent and is not affiliated with or endorsed by FreeCAD, Ollama, Alibaba Cloud (Qwen). Use it at your own risk and keep backups of your CAD files.
