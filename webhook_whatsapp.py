from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
import os
from twilio.rest import Client

# Config from environment
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM")  # e.g. whatsapp:+14155238886
ADMIN_PHONE = os.getenv("ADMIN_PHONE")                    # fallback recipient
API_KEY = os.getenv("API_KEY")                            # expected from Apps Script header x-api-key

if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM):
    raise RuntimeError("Please set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM in env")

tw_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
app = FastAPI(title="Sheet -> Twilio WhatsApp webhook")

class SheetPayload(BaseModel):
    sheet: str
    row: dict
    ts: str = None

def send_whatsapp_text(to_phone: str, body: str):
    to = f"whatsapp:{to_phone}"
    from_ = TWILIO_WHATSAPP_FROM
    try:
        msg = tw_client.messages.create(body=body, from_=from_, to=to)
        return {"ok": True, "sid": msg.sid, "status": msg.status}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def compose_message_for_row(row: dict):
    status = str(row.get("Status","")).strip().lower()
    machine = f"{row.get('Machine Name','Unknown')} ({row.get('Machine ID','')})"
    if row.get("_urgent") or status == "overdue":
        body = (f"⚠️ URGENT: {machine} requires maintenance (Overdue).\n"
                f"Service: {row.get('Service Type','')}\n"
                f"Due: {row.get('Upcoming Maintenance Date','')}\n"
                f"Remarks: {row.get('Remarks/Logs','')}")
        return "urgent", body
    if status == "due soon":
        body = (f"Reminder: {machine} maintenance due on {row.get('Upcoming Maintenance Date','')}\n"
                f"Service: {row.get('Service Type','')}\nPlease schedule.")
        return "due_soon", body
    return None, None

@app.post("/webhook/rows")
async def receive_sheet(payload: SheetPayload, x_api_key: str = Header(None)):
    # Basic auth using header
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    row = payload.row or {}
    typ, body = compose_message_for_row(row)
    if not typ:
        return {"status":"ignored", "reason":"no action required"}

    # priority: ContactPhone -> Phone -> ADMIN_PHONE
    to_phone = row.get("ContactPhone") or row.get("Phone") or ADMIN_PHONE
    if not to_phone:
        raise HTTPException(status_code=400, detail="No recipient phone found (set ContactPhone or ADMIN_PHONE)")

    result = send_whatsapp_text(to_phone, body)
    return {"status": "sent" if result.get("ok") else "error", "result": result, "type": typ}
