# Psychcast: shared inference configuration for the clinical admin

## Security and selection contract

Only `admin_clinical` can open **Mis modelos** or change the shared selection. The admin explicitly configures one provider and three model IDs: chat, analysis, and clinical copilot. There is no implicit model ID or fallback provider. Every authenticated inference request keeps its own Psychcast account identity, role checks, consent, audit trail, and patient-data authorization; only the provider/model selection is shared.

The app accepts model IDs but not arbitrary provider endpoints or commercial API keys. Anthropic and OpenAI credentials stay in Render secrets (`ANTHROPIC_API_KEY` and `OPENAI_API_KEY`). `MODEL_ALLOW_COMMERCIAL=true` is required to enable Anthropic. A missing key is reported in the settings screen; saving IDs does not make an uncredentialed provider usable.

For Local, the administrator enters the LM Studio API token. Psychcast encrypts it with the existing stable Fernet key `LLM_USER_CREDENTIALS_KEY` and keeps the ciphertext in the administrator's `llm_user_preferences` row. GET returns only a presence flag. A blank token preserves the saved value, an empty token revokes it, and a nonempty token rotates it. The input is cleared from component state after save and is never stored in browser storage.

Cloudflare Access credentials and the tunnel endpoint remain server-owned. The backend sends `CF-Access-Client-Id` and `CF-Access-Client-Secret` only to the pinned HTTPS host in Render, plus `Authorization: Bearer <decrypted LM Studio token>`. The cloudflared connector token stays on Windows and is not an HTTP credential. Missing credentials, missing model IDs, an unapproved endpoint, or unavailable selected model fail closed; Psychcast does not switch providers automatically.

## One-time operator setup

1. Keep the Windows `cloudflared` tunnel online with public hostname `ai.bfab.io` targeting `http://localhost:1234`. Keep LM Studio bound to loopback with **Require Authentication** enabled. Do not expose port 1234 publicly.
2. In Cloudflare Zero Trust, configure an Access application for `ai.bfab.io` and a Service Auth policy that includes the Render Service Token.
3. In Render's backend environment, configure `MODEL_LOCAL_BASE_URL=https://ai.bfab.io/v1`, `MODEL_LOCAL_CF_ACCESS_HOST=ai.bfab.io`, `MODEL_LOCAL_CF_ACCESS_REQUIRED=true`, `MODEL_LOCAL_CF_ACCESS_CLIENT_ID`, and `MODEL_LOCAL_CF_ACCESS_CLIENT_SECRET`. Preserve the current `LLM_USER_CREDENTIALS_KEY`; replacing it without decrypting and re-encrypting stored ciphertext will invalidate the saved LM Studio token.
4. Keep `LLM_PERSONAL_MODE=true`. The Render Blueprint sets it so authenticated requests resolve the shared admin selection. If the settings screen says shared inference is inactive, update the effective Render environment and redeploy the same frontend/backend release.
5. In **Mis modelos**, select a provider, set all three explicit model IDs, then use **Probar selección** with its synthetic `OK` request before saving. For Local, use **Actualizar modelos de LM Studio** to populate suggestions. If the tunnel catalog is unavailable, typed IDs are allowed but the connection still must pass its synthetic test.
6. No Supabase migration is needed for this settings flow; it uses the existing `llm_user_preferences` table. Existing user identities and clinical records are unchanged.

## Troubleshooting

- **Provider is unavailable:** check the status message for `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `MODEL_ALLOW_COMMERCIAL`. These are server-side settings; never paste their values into the browser or chat.
- **Local catalog cannot load:** check the Cloudflare Access service token, exact hostname, approved `https://ai.bfab.io/v1` endpoint, LM Studio authentication, and tunnel status. The app does not return those secrets.
- **HTTP 401/403:** either Cloudflare Access or LM Studio may have rejected the synthetic request. Verify each credential and policy separately; never disable Access or LM Studio authentication to work around it.
- **Model ID is rejected:** refresh the LM Studio catalog and select an ID it advertises. Model IDs for Anthropic/OpenAI must be supported by the configured server credential.

Clinical text still passes through the Render backend and Cloudflare on its way to the Windows machine. Local model weights do not make the app offline. An LM Studio token does not grant a Psychcast account, role, or access to a patient chart.
