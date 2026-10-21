import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from legaldost.api.app import create_app
from legaldost.channels.whatsapp import parse_webhook, verify_signature
from tests.conftest import RULES_TEXT, RecordingSender


def _payload(msg_id: str = "wamid.1", text: str = "hello", kind: str = "text") -> dict:
    message = {"from": "919900000000", "id": msg_id, "timestamp": "1760000000", "type": kind}
    if kind == "text":
        message["text"] = {"body": text}
    else:
        message[kind] = {"id": "media-1"}
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "1", "phone_number_id": "PNID"},
                            "contacts": [{"profile": {"name": "X"}, "wa_id": "919900000000"}],
                            "messages": [message],
                        },
                    }
                ],
            }
        ],
    }


def _signed(body: bytes, secret: str = "app-secret") -> dict[str, str]:
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={sig}", "Content-Type": "application/json"}


def test_signature_helper() -> None:
    body = b'{"a":1}'
    assert verify_signature(body, _signed(body)["X-Hub-Signature-256"], "app-secret")
    assert not verify_signature(body, "sha256=deadbeef", "app-secret")
    assert not verify_signature(body, None, "app-secret")


def test_webhook_verification_handshake(client: TestClient) -> None:
    ok = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "12345"},
    )
    assert ok.status_code == 200 and ok.text == "12345"
    bad = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"},
    )
    assert bad.status_code == 403


def test_webhook_rejects_bad_signature(client: TestClient) -> None:
    body = json.dumps(_payload()).encode()
    r = client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=00", "Content-Type": "application/json"},
    )
    assert r.status_code == 401


def test_webhook_processes_once_despite_retries(make_services, corpus) -> None:
    sender = RecordingSender()
    client = TestClient(create_app(make_services(sender=sender)))
    body = json.dumps(_payload("wamid.dup", "In Karnataka my car has film pasted on windows. Fine?")).encode()
    for _ in range(3):  # Meta retries deliver the same message id
        assert client.post("/webhooks/whatsapp", content=body, headers=_signed(body)).status_code == 200
    assert len({b for _, b in sender.sent}) >= 1
    recipients = [to for to, _ in sender.sent]
    assert set(recipients) == {"919900000000"}
    # one logical reply (possibly split in parts) for the single message id
    assert sum(1 for _, b in sender.sent if "LegalDost" in b) == 1


def test_status_updates_are_ignored_and_media_declined(make_services) -> None:
    sender = RecordingSender()
    client = TestClient(create_app(make_services(sender=sender)))
    status_only = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {"field": "messages", "value": {"statuses": [{"id": "wamid.x", "status": "delivered"}]}}
                ]
            }
        ],
    }
    body = json.dumps(status_only).encode()
    assert client.post("/webhooks/whatsapp", content=body, headers=_signed(body)).status_code == 200
    assert sender.sent == []
    body = json.dumps(_payload("wamid.img", kind="image")).encode()
    client.post("/webhooks/whatsapp", content=body, headers=_signed(body))
    assert sender.sent and "can't read image" in sender.sent[0][1]


def test_unsigned_requests_need_explicit_dev_flag(make_services) -> None:
    body = json.dumps(_payload("wamid.u")).encode()
    prod_like = TestClient(create_app(make_services(whatsapp_app_secret=None)))
    assert prod_like.post("/webhooks/whatsapp", content=body).status_code == 503
    dev = TestClient(
        create_app(
            make_services(
                whatsapp_app_secret=None, environment="development", whatsapp_allow_unsigned_dev=True
            )
        )
    )
    assert dev.post("/webhooks/whatsapp", content=body).status_code == 200


def test_parse_webhook_ignores_other_objects() -> None:
    assert parse_webhook({"object": "page", "entry": []}) == []
    msgs = parse_webhook(_payload("wamid.p", "hi"))
    assert msgs[0].text == "hi" and msgs[0].wa_id == "919900000000"


def test_dev_chat_endpoint(client: TestClient, corpus) -> None:
    r = client.post("/dev/chat", json={"session_id": "abc", "message": "hello"})
    assert r.status_code == 200 and r.json()["outcome"] == "help"
    assert client.post("/dev/chat", json={"session_id": "../etc", "message": "x"}).status_code == 422
    assert client.get("/dev").status_code == 200
    assert client.get("/healthz").json()["llm_provider"].startswith("none")


def test_dev_routes_absent_in_production(make_services) -> None:
    prod = TestClient(create_app(make_services(environment="production")))
    assert prod.post("/dev/chat", json={"session_id": "a", "message": "hi"}).status_code == 404


def test_admin_auth_and_flow(make_services) -> None:
    disabled = TestClient(create_app(make_services(admin_api_token=None)))
    assert disabled.get("/admin/sources").status_code == 404
    client = TestClient(create_app(make_services()))
    assert client.get("/admin/sources", headers={"X-Admin-Token": "wrong"}).status_code == 401
    h = {"X-Admin-Token": "admin-secret"}
    spec = {
        "source_key": "admin-rules",
        "title": "Admin rules (FICTIONAL TEST FIXTURE)",
        "issuing_authority": "T",
        "document_type": "rules",
        "source_category": "primary_official",
        "jurisdiction": "IN",
        "legal_domains": ["traffic"],
        "source_url": "https://example.test/admin.txt",
    }
    assert client.post("/admin/sources", json=spec, headers=h).status_code == 200
    bad = dict(spec, source_url="http://insecure.example/x")
    assert client.post("/admin/sources", json=bad, headers=h).status_code == 422
    up = client.post(
        "/admin/sources/admin-rules/upload",
        headers=h,
        files={"file": ("../../evil.txt", RULES_TEXT.encode(), "text/plain")},
    )
    assert up.status_code == 200 and up.json()["status"] == "created"
    dup = client.post(
        "/admin/sources/admin-rules/upload",
        headers=h,
        files={"file": ("x.txt", RULES_TEXT.encode(), "text/plain")},
    )
    assert dup.json()["status"] == "duplicate"
    listed = client.get("/admin/sources", headers=h).json()
    assert listed[0]["current_passages"] > 0
    events = client.get("/admin/ingestion-events", headers=h).json()
    assert any(e["type"] == "duplicate_skipped" for e in events)
    status = client.post(
        "/admin/sources/admin-rules/status", headers=h, json={"legal_status": "superseded", "note": "test"}
    )
    assert status.json()["legal_status"] == "superseded"
