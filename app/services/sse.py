import asyncio
from fastapi.responses import StreamingResponse
from fastapi import Request

clients = set()

async def sse_events_handler(request: Request):
    queue = asyncio.Queue()
    clients.add(queue)
    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    # Check for messages with timeout to detect disconnect frequently
                    msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"event: {msg['event']}\ndata: {msg['data']}\n\n"
                except asyncio.TimeoutError:
                    pass
        finally:
            clients.remove(queue)
    return StreamingResponse(event_stream(), media_type="text/event-stream")

def broadcast_event(event_name: str, data: str = ""):
    for q in list(clients):
        q.put_nowait({"event": event_name, "data": data})
