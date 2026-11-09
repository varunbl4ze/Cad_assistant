from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from router import execute_command

app = FastAPI(title="CAD Automation Assistant")


class CommandRequest(BaseModel):
    command: str
    parameters: dict = {}



@app.get("/")
def home():
    return {
        "app": "CAD Automation Assistant",
        "status": "running"
    }


@app.get("/health")
def health_check():
    return {"status": "running"}





@app.post("/execute")
def execute(request: CommandRequest):
    try:
        result = execute_command(
            request.command,
            request.parameters
        )
        return {"success": True, "result": result}

    except (ValueError, TypeError) as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )