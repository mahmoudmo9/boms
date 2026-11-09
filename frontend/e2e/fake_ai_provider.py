"""A fake OpenAI-compatible AI provider for the v0.9.0 browser check (standard library only, 127.0.0.1, no network).

BOMS is configured with an «OpenAI-compatible» provider at http://127.0.0.1:<port>; this server answers
``POST /v1/chat/completions`` with recorded responses chosen by the prompt (item extraction, an offer, a party, a
draft message, the connection test). Usage: python e2e/fake_ai_provider.py 8799"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ITEMS = {"items": [
    {"original": "Centrifugal pump API 610, Q=120 m3/h, H=85 m — 2 sets", "noun": "PUMP", "template": "pump",
     "attributes": {"type": "centrifugal", "standard": "API 610", "flow": "120", "head": "85"}, "quantity": 2, "unit": "SET",
     "specs": [{"key": "Seal", "value": "API 682 Plan 53B"}], "hs_code": "841370", "hs_reason": "centrifugal pumps for liquids",
     "standards": ["API 610"], "page": 1, "confidence": "high"},
    {"original": "Gate valve 6\" class 300 WCB — 4 pcs", "noun": "VALVE", "template": "valve",
     "attributes": {"type": "gate", "size": "6", "rating": "300", "material": "cs"}, "quantity": 4, "unit": "H87",
     "hs_code": "848180", "hs_reason": "valves", "page": 1, "confidence": "high"}],
    "terms": {"incoterm": "CFR", "incoterm_place": "Bandar Abbas"}, "column_mapping": None}
OFFER = {"items": [
    {"original": "Item 1 as requested", "noun": None, "template": None, "attributes": {}, "quantity": 2, "unit": "H87",
     "line_item": 1, "unit_price": "1200", "total": "2400", "page": None, "confidence": "high", "lead_time_days": 45},
    {"original": "Item 2 as requested", "noun": None, "template": None, "attributes": {}, "quantity": 4, "unit": "H87",
     "line_item": 2, "unit_price": "300", "total": "1300", "page": None, "confidence": "high", "lead_time_days": 30}],
    "terms": {"currency": "USD", "incoterm": "FOB", "incoterm_place": "Shanghai", "valid_until": "2027-03-31",
              "payment_terms": "30% advance, 70% before shipment"}, "column_mapping": None}
PARTY = {"company": {"name": "Ningbo Flow Equipment Co., Ltd.", "legal_form": "Co., Ltd.", "country_iso2": "CN",
                     "website": "https://flow.example"},
         "person": {"name": "Wang Wei", "title": "Sales manager", "phones": ["+86 574 8888 1234"], "emails": ["wang@flow.example"]}}
DRAFT = {"subject": "Request for Quotation", "body": "Dear Sir or Madam,\nPlease quote the items below.\nBest regards",
         "back_translation_fa": "با سلام، لطفاً برای اقلام زیر قیمت بدهید. با احترام"}


def answer(body: dict) -> str:
    text = json.dumps(body.get("messages", []), ensure_ascii=False)
    if "connection check" in text:
        return "OK"
    if "You extract the items" in text:
        return json.dumps(OFFER if "Target: offer" in text else ITEMS, ensure_ascii=False)
    if "e-mail signature" in text:
        return json.dumps(PARTY, ensure_ascii=False)
    if "You draft business messages" in text:
        return json.dumps(DRAFT, ensure_ascii=False)
    return "{}"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        out = {"choices": [{"message": {"content": answer(body)}}], "usage": {"prompt_tokens": 800, "completion_tokens": 200}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8799), Handler).serve_forever()
