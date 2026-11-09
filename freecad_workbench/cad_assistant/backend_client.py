"""
backend_client.py - talks to the FastAPI backend. No UI code lives here.

This file knows nothing about Qt, so you can test it from any Python:
    python -c "from cad_assistant.backend_client import *; print(check_health(get_backend_url()))"
"""

import json
import urllib.error
import urllib.request

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"

# FreeCAD stores user settings in a "parameter" tree. This is our own branch.
_PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/CADAssistant"


def get_backend_url():
    """Return the backend URL: the saved setting, or the default."""
    try:
        import FreeCAD  # only available inside FreeCAD
        url = FreeCAD.ParamGet(_PARAM_PATH).GetString("BackendUrl", DEFAULT_BACKEND_URL)
    except ImportError:
        url = DEFAULT_BACKEND_URL
    return (url or DEFAULT_BACKEND_URL).strip().rstrip("/")


def set_backend_url(url):
    """Save a new backend URL and return it. Raises ValueError if it isn't http(s)."""
    url = url.strip().rstrip("/")
    problem = url_problem(url)
    if problem:
        raise ValueError(problem)
    import FreeCAD
    FreeCAD.ParamGet(_PARAM_PATH).SetString("BackendUrl", url)
    return url


def url_problem(base_url):
    """Return an error message if the URL is unusable, otherwise None."""
    # Only allow http(s). urllib would also accept file:// URLs, which we don't want.
    if not base_url.lower().startswith(("http://", "https://")):
        return "Backend URL must start with http:// or https://"
    return None


def _opener():
    # An empty ProxyHandler means "ignore system proxy settings" so a local
    # backend on 127.0.0.1 is not sent through a corporate proxy.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def check_health(base_url, timeout=3):
    """
    Call GET <base_url>/health.

    Always returns a dict and never raises:
        {"ok": True,  "message": "Connected"}
        {"ok": False, "message": "<human-readable reason>"}
    """
    problem = url_problem(base_url)
    if problem:
        return {"ok": False, "message": problem}

    try:
        with _opener().open(base_url + "/health", timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        if isinstance(body, dict) and body.get("status") == "running":
            return {"ok": True, "message": "Connected"}
        return {"ok": False, "message": "Unexpected response from /health"}

    except urllib.error.HTTPError as error:  # server answered with an error code
        return {"ok": False, "message": "Backend returned HTTP %s" % error.code}
    except urllib.error.URLError as error:  # nobody listening, wrong host, etc.
        return {
            "ok": False,
            "message": "Cannot reach backend at %s (%s). Is it running?" % (base_url, error.reason),
        }
    except Exception as error:  # timeouts, bad JSON, anything else
        return {"ok": False, "message": "Backend check failed: %s" % error}


def execute_command(base_url, command, parameters, timeout=5):
    """
    Call POST <base_url>/execute, which your backend's router handles.

    Always returns a dict and never raises:
        {"ok": True,  "result": {...whatever the backend returned...}}
        {"ok": False, "message": "<human-readable reason>"}
    """
    problem = url_problem(base_url)
    if problem:
        return {"ok": False, "message": problem}

    request = urllib.request.Request(
        base_url + "/execute",
        data=json.dumps({"command": command, "parameters": parameters}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _opener().open(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        if isinstance(body, dict) and body.get("success"):
            return {"ok": True, "result": body.get("result", {})}
        return {"ok": False, "message": "Backend did not report success"}

    except urllib.error.HTTPError as error:
        # Your backend answers bad input with HTTP 400 and {"detail": "..."}.
        detail = ""
        try:
            detail = json.loads(error.read().decode("utf-8")).get("detail", "")
        except Exception:
            pass
        return {"ok": False, "message": str(detail) or "Backend returned HTTP %s" % error.code}
    except urllib.error.URLError as error:
        return {
            "ok": False,
            "message": "Cannot reach backend at %s (%s). Is it running?" % (base_url, error.reason),
        }
    except Exception as error:
        return {"ok": False, "message": "Backend request failed: %s" % error}