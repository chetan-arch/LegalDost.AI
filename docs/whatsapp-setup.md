# Connecting a real WhatsApp number (WhatsApp Business Platform – Cloud API)

Status: the adapter is implemented and tested with signed fixture payloads and a mocked Graph API.
It has **not** been tested against Meta, because no credentials were available. Check every step
below against Meta's current documentation; platform rules and Graph API versions change.

Official references:
* Cloud API overview & get started: <https://developers.facebook.com/docs/whatsapp/cloud-api>
* Webhooks (verification + `X-Hub-Signature-256`): <https://developers.facebook.com/docs/graph-api/webhooks/getting-started>
* Webhook setup for WhatsApp: <https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks>
* Messaging policy, opt-in and conversation rules: <https://developers.facebook.com/docs/whatsapp/overview>

## 1. Meta side

1. Create a Meta developer app of type **Business** and add the **WhatsApp** product.
2. Attach (or create) a WhatsApp Business Account and register the phone number you will use.
   Note its **Phone number ID** (not the phone number itself).
3. Create a **System User** in Business Settings, give it access to the app and WABA, and generate
   a long-lived token with the WhatsApp messaging/management permissions. Do not use the
   24-hour temporary token in production.
4. Copy the **App secret** (App settings → Basic). It is used to verify webhook signatures.
5. Choose a random **verify token** (any long random string).
6. Configure the webhook: callback URL `https://<your-host>/webhooks/whatsapp`, verify token from
   step 5, then subscribe the app to the WABA's **messages** field.
7. Complete business verification and display-name approval before going live.

## 2. Server side

```bash
WHATSAPP_ENABLED=true
WHATSAPP_VERIFY_TOKEN=<step 5>
WHATSAPP_APP_SECRET=<step 4>
WHATSAPP_ACCESS_TOKEN=<step 3>
WHATSAPP_PHONE_NUMBER_ID=<step 2>
WHATSAPP_GRAPH_API_VERSION=v23.0   # set to a version listed as available in Meta's changelog
USER_ID_HASH_SECRET=<long random value>
```

The server must be reachable over public HTTPS. For local testing use a tunnel you trust and
remove it afterwards.

## 3. What the code does

| Concern | Implementation |
|---|---|
| Verification GET | `hub.mode == "subscribe"` and constant-time match of `hub.verify_token`; echoes `hub.challenge` as plain text. 403 otherwise, 503 when not configured. |
| Authenticity | `X-Hub-Signature-256: sha256=HMAC_SHA256(app_secret, raw_body)` checked on the **raw** bytes before JSON parsing; 401 on mismatch. Unsigned requests are rejected unless `ENVIRONMENT=development` **and** `WHATSAPP_ALLOW_UNSIGNED_DEV=true`. |
| Retries / duplicates | Each message id (`wamid…`) is inserted into `processed_events`; repeats are acknowledged with 200 but not processed again. |
| Fast acknowledgement | Returns 200 immediately; processing and the reply happen in a background task. |
| Status callbacks | `statuses` (sent/delivered/read) are ignored. |
| Media | Image, audio, document, video: polite "can't read this yet" reply (see `channels/media.py`). |
| Outbound | `POST https://graph.facebook.com/{version}/{phone_number_id}/messages` with `messaging_product=whatsapp`, `type=text`; bounded retries on 429/5xx; replies split at 4096 characters. |
| Messaging window | Only replies to user messages are sent, i.e. inside the customer-service window opened by the user. Business-initiated (template) messages are **not implemented**. |
| Identifiers | The sender's `wa_id` is used only in memory to reply; the database stores an HMAC of it. |

## 4. Known gaps before production

* Background tasks run in-process: a crash between acknowledgement and reply loses that reply
  (the message id is already marked processed, which avoids duplicate replies). Use a durable
  queue (e.g. a jobs table or Redis) for production.
* Rate limiting is in-memory per process.
* No template messages, no read receipts, no media download.
* Opt-in, privacy notice wording and data-processing terms with Meta need legal review (see
  `docs/privacy-and-dpdp.md`).
