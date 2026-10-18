import { useEffect, useState } from "react";
import { api } from "../api";
import PsychcastLoader from "../components/PsychcastLoader";

type Provider = "anthropic" | "openai" | "openai_compatible";
type Busy = "" | "save" | "test" | "remove" | "models";

interface LocalModel {
  id: string;
  loaded: boolean;
}

interface PersonalStatus {
  configured: boolean;
  provider: Provider | "";
  chat_model: string;
  analysis_model: string;
  copilot_model: string;
  max_tokens: number;
  timeout_seconds: number;
  local_available: boolean;
  lm_api_key_configured: boolean;
  local_models: LocalModel[];
  local_models_reachable: boolean;
  ready: boolean;
  anthropic_allowed: boolean;
  anthropic_api_key_configured: boolean;
  openai_allowed: boolean;
  openai_api_key_configured: boolean;
  shared_inference_active: boolean;
}

interface CatalogResult {
  models: LocalModel[];
  reachable: boolean;
  detail: string;
}

const PROVIDER_LABEL: Record<Provider, string> = {
  openai_compatible: "Local · LM Studio",
  anthropic: "Anthropic",
  openai: "OpenAI · Codex / ChatGPT API",
};

const endpoint = "/api/v1/settings/llm/personal";

export default function SettingsPage() {
  const [status, setStatus] = useState<PersonalStatus | null>(null);
  const [provider, setProvider] = useState<Provider | "">("");
  const [chatModel, setChatModel] = useState("");
  const [analysisModel, setAnalysisModel] = useState("");
  const [copilotModel, setCopilotModel] = useState("");
  const [maxTokens, setMaxTokens] = useState(4096);
  const [timeoutSeconds, setTimeoutSeconds] = useState(120);
  const [localModels, setLocalModels] = useState<LocalModel[]>([]);
  const [catalogReachable, setCatalogReachable] = useState(false);
  const [lmApiKey, setLmApiKey] = useState("");
  const [revokeLmKey, setRevokeLmKey] = useState(false);
  const [busy, setBusy] = useState<Busy>("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    api.get<PersonalStatus>(endpoint)
      .then((next) => {
        setStatus(next);
        setProvider(next.provider);
        setChatModel(next.chat_model);
        setAnalysisModel(next.analysis_model);
        setCopilotModel(next.copilot_model);
        setMaxTokens(next.max_tokens);
        setTimeoutSeconds(next.timeout_seconds);
        setLocalModels(next.local_models ?? []);
        setCatalogReachable(next.local_models_reachable);
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  function clearFeedback() {
    setError("");
    setMessage("");
  }

  function candidate() {
    if (!provider) throw new Error("Selecciona un proveedor.");
    return {
      provider,
      chat_model: chatModel.trim(),
      analysis_model: analysisModel.trim(),
      copilot_model: copilotModel.trim(),
      max_tokens: maxTokens,
      timeout_seconds: timeoutSeconds,
      lm_api_key: provider === "openai_compatible"
        ? (revokeLmKey ? "" : (lmApiKey.trim() || null))
        : null,
    };
  }

  function acceptStatus(next: PersonalStatus) {
    setStatus(next);
    setProvider(next.provider);
    setChatModel(next.chat_model);
    setAnalysisModel(next.analysis_model);
    setCopilotModel(next.copilot_model);
    setMaxTokens(next.max_tokens);
    setTimeoutSeconds(next.timeout_seconds);
    setLocalModels(next.local_models ?? []);
    setCatalogReachable(next.local_models_reachable);
  }

  async function save() {
    if (!status) return;
    setBusy("save");
    clearFeedback();
    try {
      const next = await api.put<PersonalStatus>(endpoint, candidate());
      acceptStatus(next);
      setLmApiKey("");
      setRevokeLmKey(false);
      setMessage("Configuración compartida guardada para todos los usuarios.");
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function test() {
    setBusy("test");
    clearFeedback();
    try {
      const result = await api.post<{ ok: boolean; detail: string }>(endpoint + "/test", candidate());
      if (result.ok) setMessage(result.detail);
      else setError(result.detail);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function loadModels() {
    setBusy("models");
    clearFeedback();
    try {
      const result = await api.post<CatalogResult>(endpoint + "/models", {
        lm_api_key: lmApiKey.trim() || null,
      });
      setLocalModels(result.models);
      setCatalogReachable(result.reachable);
      if (result.reachable) setMessage(result.detail);
      else setError(result.detail);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function remove() {
    if (!window.confirm("¿Eliminar la configuración compartida? Los usuarios dejarán de tener un proveedor y modelos seleccionados.")) return;
    setBusy("remove");
    clearFeedback();
    try {
      const next = await api.del<PersonalStatus>(endpoint);
      acceptStatus(next);
      setLmApiKey("");
      setRevokeLmKey(false);
      setMessage("Se ha eliminado la configuración compartida.");
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy("");
    }
  }

  const local = provider === "openai_compatible";
  const hasModels = Boolean(chatModel.trim() && analysisModel.trim() && copilotModel.trim());
  const maySave = Boolean(status && provider && hasModels && (provider !== "anthropic" || status.anthropic_allowed));
  const mayTest = Boolean(provider && hasModels);
  const providerLabel = status?.provider ? PROVIDER_LABEL[status.provider] : "sin seleccionar";

  return (
    <div className="page">
      <h1>Mis modelos</h1>
      <p className="subtitle">
        Configuración compartida del administrador clínico: el proveedor y los modelos elegidos se aplican a chat, análisis y copiloto para todos los usuarios.
      </p>
      <section className="card">
        <h2>Proveedor y modelos de inferencia</h2>
        {status && (
          <p className="info">
            {status.configured
              ? `Selección compartida actual: ${providerLabel}`
              : "Todavía no hay proveedor ni modelos seleccionados."}
          </p>
        )}
        {status && !status.shared_inference_active && (
          <p className="warning" role="status">
            El backend todavía no usa esta selección compartida. En Render activa LLM_PERSONAL_MODE=true y vuelve a desplegar para que la configuración elegida se aplique a las peticiones autenticadas.
          </p>
        )}
        {status && (
          <>
            <label className="field" htmlFor="model-provider">
              <span>Proveedor</span>
              <select id="model-provider" value={provider} disabled={busy !== ""} onChange={(event) => {
                setProvider(event.target.value as Provider | "");
                setRevokeLmKey(false);
                clearFeedback();
              }}>
                <option value="">Selecciona un proveedor</option>
                <option value="openai_compatible">Local · LM Studio por Cloudflare</option>
                <option value="anthropic" disabled={!status.anthropic_allowed}>Anthropic</option>
                <option value="openai">OpenAI · Codex / ChatGPT API</option>
              </select>
            </label>

            {provider && (
              <>
                {local && (
                  <>
                    <p className="info">
                      El servidor conecta con LM Studio mediante el túnel aprobado. La API key de LM Studio se cifra en el backend; las credenciales de Cloudflare permanecen en Render.
                    </p>
                    {!status.local_available && (
                      <p className="warning" role="status">
                        Falta preparar el acceso local en el servidor. Configura en Render MODEL_LOCAL_BASE_URL, MODEL_LOCAL_CF_ACCESS_HOST, MODEL_LOCAL_CF_ACCESS_REQUIRED=true, MODEL_LOCAL_CF_ACCESS_CLIENT_ID, MODEL_LOCAL_CF_ACCESS_CLIENT_SECRET y LLM_USER_CREDENTIALS_KEY.
                      </p>
                    )}
                    <label className="field" htmlFor="personal-lm-api-key">
                      <span>API key de LM Studio</span>
                      <input
                        id="personal-lm-api-key"
                        type="password"
                        autoComplete="new-password"
                        value={lmApiKey}
                        disabled={busy !== "" || revokeLmKey}
                        placeholder={status.lm_api_key_configured ? "Configurada · deja vacío para conservar" : "API key de LM Studio"}
                        onChange={(event) => {
                          setLmApiKey(event.target.value);
                          clearFeedback();
                        }}
                      />
                      <span className="meta">
                        {status.lm_api_key_configured ? "Configurada en el backend." : "Aún no configurada."} Nunca se muestra de nuevo ni se guarda en el navegador.
                      </span>
                    </label>
                    <div className="alert-actions">
                      <button className="btn-secondary" disabled={busy !== ""} onClick={loadModels}>
                        {busy === "models" ? "Consultando…" : "Actualizar modelos de LM Studio"}
                      </button>
                    </div>
                    {!catalogReachable && (
                      <p className="warning" role="status">
                        No se pudo leer el catálogo. Puedes escribir los IDs exactos que anuncia LM Studio y probarlos antes de guardar.
                      </p>
                    )}
                    {status.lm_api_key_configured && (
                      <label className="field">
                        <span>
                          <input type="checkbox" checked={revokeLmKey} disabled={busy !== ""} onChange={(event) => {
                            setRevokeLmKey(event.target.checked);
                            clearFeedback();
                          }} />{" "}
                          Revocar la API key de LM Studio al guardar
                        </span>
                      </label>
                    )}
                  </>
                )}

                {provider === "anthropic" && status.anthropic_allowed && !status.anthropic_api_key_configured && (
                  <p className="warning" role="status">
                    Puedes guardar los IDs, pero falta ANTHROPIC_API_KEY en los secretos del servidor para probar y usar Anthropic.
                  </p>
                )}
                {provider === "anthropic" && !status.anthropic_allowed && (
                  <p className="warning" role="status">
                    Anthropic está bloqueado por la política del despliegue. Habilita MODEL_ALLOW_COMMERCIAL=true en Render.
                  </p>
                )}
                {provider === "openai" && !status.openai_api_key_configured && (
                  <p className="warning" role="status">
                    Puedes guardar los IDs, pero falta OPENAI_API_KEY en los secretos del servidor para probar y usar OpenAI.
                  </p>
                )}

                <datalist id="local-model-catalog">
                  {localModels.map((model) => (
                    <option key={model.id} value={model.id} label={model.loaded ? "cargado en LM Studio" : "anunciado por LM Studio"} />
                  ))}
                </datalist>
                <label className="field" htmlFor="chat-model">
                  <span>Modelo de chat</span>
                  <input id="chat-model" list={local ? "local-model-catalog" : undefined} value={chatModel} disabled={busy !== ""} placeholder="ID exacto del modelo" onChange={(event) => { setChatModel(event.target.value); clearFeedback(); }} />
                </label>
                <label className="field" htmlFor="analysis-model">
                  <span>Modelo de análisis</span>
                  <input id="analysis-model" list={local ? "local-model-catalog" : undefined} value={analysisModel} disabled={busy !== ""} placeholder="ID exacto del modelo" onChange={(event) => { setAnalysisModel(event.target.value); clearFeedback(); }} />
                </label>
                <label className="field" htmlFor="copilot-model">
                  <span>Modelo del copiloto clínico</span>
                  <input id="copilot-model" list={local ? "local-model-catalog" : undefined} value={copilotModel} disabled={busy !== ""} placeholder="ID exacto del modelo" onChange={(event) => { setCopilotModel(event.target.value); clearFeedback(); }} />
                </label>

                <div className="field-row">
                  <label className="field" htmlFor="model-max-tokens">
                    <span>Máximo de tokens</span>
                    <input id="model-max-tokens" type="number" min={256} max={32768} step={256} value={maxTokens} disabled={busy !== ""} onChange={(event) => setMaxTokens(Number(event.target.value))} />
                  </label>
                  <label className="field" htmlFor="model-timeout">
                    <span>Tiempo de espera (segundos)</span>
                    <input id="model-timeout" type="number" min={5} max={5000} step={5} value={timeoutSeconds} disabled={busy !== ""} onChange={(event) => setTimeoutSeconds(Number(event.target.value))} />
                  </label>
                </div>
                <p className="meta">No hay modelos preseleccionados. Guarda IDs explícitos para las tres funciones; las credenciales comerciales y de Cloudflare no se exponen en esta pantalla.</p>
              </>
            )}

            <div className="alert-actions">
              <button disabled={busy !== "" || !maySave} onClick={save}>{busy === "save" ? "Guardando…" : "Guardar configuración"}</button>
              <button className="btn-secondary" disabled={busy !== "" || !mayTest} onClick={test}>{busy === "test" ? "Probando…" : "Probar selección"}</button>
              <button className="btn-secondary" disabled={busy !== "" || !status.configured} onClick={remove}>Eliminar configuración compartida</button>
            </div>
          </>
        )}
        {busy === "test" && <PsychcastLoader size="sm" label="Probando con una solicitud sintética…" />}
        {error && <p className="error" role="alert">{error}</p>}
        {message && <p className="info" role="status">{message}</p>}
        <p className="meta">La prueba usa solo el texto sintético «OK». Si el proveedor falla, Psychcast no envía la solicitud a otro proveedor.</p>
      </section>
    </div>
  );
}
