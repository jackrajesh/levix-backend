import asyncio
import json
from fastapi import Request
from fastapi.responses import StreamingResponse

# =================================================================
# LEVIX REAL-TIME EVENT BUS (SSE)
# =================================================================
# Dictionary mapping shop_id (int) -> set of asyncio.Queue
# This is a singleton state for the current process.
shop_queues = {}

async def sse_events_handler(request: Request, shop_id: int):
    """
    Handles a long-lived SSE connection for a specific shop.
    Delivers real-time signals without polling.
    """
    queue = asyncio.Queue()
    
    # Register the unique connection for this shop
    if shop_id not in shop_queues:
        shop_queues[shop_id] = set()
    shop_queues[shop_id].add(queue)
    
    async def event_stream():
        try:
            # 1. Initial Handshake
            print(f"[SSE] Connection established for Shop {shop_id}")
            yield f"event: connected\ndata: {json.dumps({'status': 'live', 'shop_id': shop_id})}\n\n"
            
            while True:
                # 2. Check for client disconnection
                if await request.is_disconnected():
                    break
                
                try:
                    # 3. Wait for an event with a keep-alive timeout
                    msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                    
                    event_type = msg.get("event", "message")
                    event_data = msg.get("data", "")
                    
                    print(f"[SSE] Pushing '{event_type}' to Shop {shop_id}")
                    yield f"event: {event_type}\ndata: {event_data}\n\n"
                    
                except asyncio.TimeoutError:
                    # 4. Stay-alive Ping (Prevents timeouts in proxies/load balancers)
                    yield ": ping\n\n"
                    
        except Exception as e:
            print(f"[SSE] Stream error for Shop {shop_id}: {e}")
        finally:
            # 5. Guaranteed Cleanup
            print(f"[SSE] Connection closed/dropped for Shop {shop_id}")
            if shop_id in shop_queues:
                shop_queues[shop_id].discard(queue)
                if not shop_queues[shop_id]:
                    del shop_queues[shop_id]
                    
    return StreamingResponse(
        event_stream(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
        }
    )

def broadcast_event(shop_id: int, event_name: str, data: str = ""):
    """
    Triggers a real-time update across all active dashboard connections
    for the specific shop_id.
    """
    target_id = int(shop_id)
    print(f"[SSE] Broadcasting '{event_name}' -> Shop {target_id}")
    
    if target_id in shop_queues:
        for q in list(shop_queues[target_id]):
            try:
                q.put_nowait({"event": event_name, "data": data})
            except Exception as e:
                print(f"[SSE] Failed to put message in queue for Shop {target_id}: {e}")
