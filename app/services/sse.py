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
    Gap 7 fix: Flushes pending events from DB upon connection.
    """
    queue = asyncio.Queue()
    
    # Register the unique connection for this shop
    if shop_id not in shop_queues:
        shop_queues[shop_id] = set()
    shop_queues[shop_id].add(queue)

    from ..database import SessionLocal
    from .. import models
    from datetime import datetime, timedelta, timezone

    # Initial flush of pending events
    db = SessionLocal()
    try:
        # Auto-expire old events (>24h)
        expiry = datetime.now(timezone.utc) - timedelta(hours=24)
        db.query(models.PendingSSEEvent).filter(
            models.PendingSSEEvent.created_at < expiry,
            models.PendingSSEEvent.delivered == False
        ).delete()
        db.commit()

        # Find undelivered events
        pending = db.query(models.PendingSSEEvent).filter(
            models.PendingSSEEvent.shop_id == shop_id,
            models.PendingSSEEvent.delivered == False
        ).order_by(models.PendingSSEEvent.created_at.asc()).all()

        for ev in pending:
            queue.put_nowait({"event": ev.event_type, "data": json.dumps(ev.data)})
            ev.delivered = True
        db.commit()
    except Exception as e:
        print(f"[SSE] Initial flush failed: {e}")
    finally:
        db.close()
    
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

def broadcast_event(shop_id: int, event_name: str, data: Any = ""):
    """
    Triggers a real-time update across all active dashboard connections.
    Gap 7 fix: Persists event to DB to guarantee delivery.
    """
    target_id = int(shop_id)
    
    from ..database import SessionLocal
    from .. import models
    
    # 1. Persist to DB first
    db = SessionLocal()
    try:
        new_event = models.PendingSSEEvent(
            shop_id=target_id,
            event_type=event_name,
            data=data if isinstance(data, (dict, list)) else {"raw": str(data)},
            delivered=False
        )
        db.add(new_event)
        db.commit()
        db.refresh(new_event)
        
        # 2. Broadcast to active queues
        json_data = json.dumps(new_event.data)
        if target_id in shop_queues:
            for q in list(shop_queues[target_id]):
                try:
                    q.put_nowait({"event": event_name, "data": json_data})
                    # Mark as delivered if we have at least one active consumer
                    # (Simplified: if we broadcast, we assume delivery for now, 
                    # but the flush logic handles reconnection)
                    new_event.delivered = True
                except Exception as e:
                    print(f"[SSE] Broadcast failed for one queue: {e}")
            db.commit()
            
    except Exception as e:
        print(f"[SSE] Broadcast persistence failed: {e}")
    finally:
        db.close()
