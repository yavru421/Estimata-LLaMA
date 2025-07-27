
from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from integrata_llama import IntegrataLlama

app = FastAPI()
llama = IntegrataLlama()

class ReasonRequest(BaseModel):
    input: str
    context: Optional[dict] = None

def sequential_reasoning(user_input: str, context: Optional[dict] = None) -> Dict[str, Any]:
    """
    Uses the actual LLaMA model (via IntegrataLlama) to deliberate and select the right tool or action.
    For now, uses simple rules, but can be extended to use LLaMA for chain-of-thought.
    """
    steps: List[str] = []
    result = None
    lowered = user_input.lower()
    if "moderate" in lowered or "safe" in lowered:
        steps.append("Detected moderation request. Calling moderate().")
        result = llama.moderate(user_input)
    elif "search" in lowered or "web" in lowered:
        steps.append("Detected web search request. Calling web_search().")
        result = llama.web_search(user_input)
    elif "weather" in lowered:
        steps.append("Detected weather tool call. Calling tool_call('get_weather').")
        result = llama.tool_call("get_weather", user_input)
    else:
        steps.append("Defaulting to chat().")
        result = llama.chat(user_input)
    return {"result": result, "reasoning_steps": steps}

@app.post("/reason")
def reason_endpoint(req: ReasonRequest):
    output = sequential_reasoning(req.input, req.context)
    return output

class ChatRequest(BaseModel):
    message: str
    stream: Optional[bool] = False

class ModerateRequest(BaseModel):
    content: str

class WebSearchRequest(BaseModel):
    query: str
    max_results: Optional[int] = 8

class ToolCallRequest(BaseModel):
    tool_name: str
    args: Optional[list] = []
    kwargs: Optional[dict] = {}

@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    stream = req.stream if req.stream is not None else False
    return {"response": llama.chat(req.message, stream=stream)}

@app.post("/moderate")
def moderate_endpoint(req: ModerateRequest):
    return {"response": llama.moderate(req.content)}

@app.post("/web_search")
def web_search_endpoint(req: WebSearchRequest):
    max_results = req.max_results if req.max_results is not None else 8
    return {"response": llama.web_search(req.query, max_results=max_results)}

@app.post("/tool_call")
def tool_call_endpoint(req: ToolCallRequest):
    return {"response": llama.tool_call(req.tool_name, *(req.args or []), **(req.kwargs or {}))}

@app.get("/")
def root():
    return {"message": "IntegrataLlama API is running."}
