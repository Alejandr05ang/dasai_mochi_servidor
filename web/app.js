const serverUrlInput = document.getElementById("serverUrl");
const connectBtn = document.getElementById("connectBtn");
const clearBtn = document.getElementById("clearBtn");
const connectionDot = document.getElementById("connectionDot");
const connectionStatus = document.getElementById("connectionStatus");
const statusNote = document.getElementById("statusNote");
const eventList = document.getElementById("eventList");
const eventCount = document.getElementById("eventCount");
const lastTranscript = document.getElementById("lastTranscript");
const lastIntent = document.getElementById("lastIntent");

let socket = null;
let reconnectTimer = null;
let reconnectAttempts = 0;
let totalEvents = 0;

const STORAGE_KEY = "voice-iot-dashboard-state";
let eventHistory = [];

function persistState() {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        totalEvents,
        eventHistory,
        lastTranscript: lastTranscript.textContent,
        lastIntent: lastIntent.textContent,
      })
    );
  } catch {
    // Ignore storage errors in private mode or blocked storage.
  }
}

function restoreState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return;
    }

    const saved = JSON.parse(raw);
    totalEvents = Number(saved.totalEvents) || 0;
    eventCount.textContent = String(totalEvents);
    lastTranscript.textContent = saved.lastTranscript || "—";
    lastIntent.textContent = saved.lastIntent || "—";
    eventHistory = Array.isArray(saved.eventHistory) ? saved.eventHistory : [];

    for (const entry of eventHistory.slice().reverse()) {
      renderStoredEvent(entry.type, entry.payload);
    }
  } catch {
    eventHistory = [];
  }
}

function setStatus(state, note) {
  connectionDot.classList.remove("connected", "connecting");
  if (state === "connected") {
    connectionDot.classList.add("connected");
    connectionStatus.textContent = "Conectado";
  } else if (state === "connecting") {
    connectionDot.classList.add("connecting");
    connectionStatus.textContent = "Conectando";
  } else {
    connectionStatus.textContent = "Desconectado";
  }
  statusNote.textContent = note;
}

function appendEvent(type, payload, shouldPersist = true) {
  totalEvents += 1;
  eventCount.textContent = String(totalEvents);

  renderEvent(type, payload, new Date().toLocaleTimeString());

  eventHistory.unshift({ type, payload });
  if (eventHistory.length > 30) {
    eventHistory = eventHistory.slice(0, 30);
  }

  if (shouldPersist) {
    persistState();
  }

  while (eventList.children.length > 30) {
    eventList.removeChild(eventList.lastElementChild);
  }
}

function renderEvent(type, payload, timeLabel) {
  const item = document.createElement("article");
  item.className = "event-item";

  const meta = document.createElement("div");
  meta.className = "event-meta";

  const badge = document.createElement("span");
  badge.className = `badge ${type}`;
  badge.textContent = type;

  const source = document.createElement("span");
  source.textContent = timeLabel;

  meta.append(badge, source);

  const content = document.createElement("div");
  if ((type === "audio_file" || type === "session_result") && payload && typeof payload === "object" && payload.file) {
    const audio = document.createElement("audio");
    audio.controls = true;

    const wsUrlForAudio = serverUrlInput.value.trim();
    const apiBaseForAudio = wsUrlForAudio.replace(/^ws/, "http").replace(/\/ws$/, "");
    audio.src = (apiBaseForAudio || "http://localhost:8000") + payload.file;

    const caption = document.createElement("div");
    caption.textContent = payload.file;
    caption.style.color = "var(--muted)";
    caption.style.fontSize = "0.9rem";
    caption.style.marginTop = "8px";

    content.append(audio, caption);
  } else {
    content.textContent = typeof payload === "string" ? payload : JSON.stringify(payload);
  }

  item.append(meta, content);
  eventList.prepend(item);
}

function renderStoredEvent(type, payload) {
  const ts = payload && typeof payload === "object" && payload.time ? new Date(payload.time).toLocaleTimeString() : "guardado";
  renderEvent(type, payload, ts);
}

function handleMessage(data) {
  const type = data.type || "status";

  if (type === "session_result") {
    appendEvent(type, data);
    const transcriptText = (data.transcription && data.transcription.text) ? data.transcription.text : "(sin texto detectado)";
    lastTranscript.textContent = transcriptText;
    persistState();
    return;
  }

  if (type === "transcription" && data.text) {
    appendEvent(type, data);
    lastTranscript.textContent = data.text;
    persistState();
    return;
  }

  if (type === "intent" && data.intent) {
    appendEvent(type, data);
    lastIntent.textContent = data.intent;
    persistState();
    return;
  }

  if (type === "audio_file" && data.url) {
    data.file = data.url;
    appendEvent(type, data);
    persistState();
    return;
  }

  appendEvent(type, data);
}

function clearEvents() {
  eventList.innerHTML = "";
  totalEvents = 0;
  eventHistory = [];
  eventCount.textContent = "0";
  lastTranscript.textContent = "—";
  lastIntent.textContent = "—";
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    socket.close();
  }

  const url = serverUrlInput.value.trim();
  if (!url) {
    setStatus("disconnected", "Ingresa una URL de WebSocket válida.");
    return;
  }

  setStatus("connecting", "Intentando conectar con el servidor...");
  socket = new WebSocket(url);

  socket.addEventListener("open", () => {
    reconnectAttempts = 0;
    setStatus("connected", "Conectado al servidor. Esperando eventos...");
    connectBtn.textContent = "Reconectar";
  });

  socket.addEventListener("message", (event) => {
    try {
      const data = JSON.parse(event.data);
      handleMessage(data);
    } catch {
      appendEvent("status", event.data);
    }
  });

  socket.addEventListener("close", () => {
    setStatus("disconnected", "La conexión se cerró. Pulsa Conectar para volver a abrirla.");
  });

  socket.addEventListener("error", () => {
    setStatus("disconnected", "No se pudo conectar con el servidor.");
  });
}

function scheduleReconnect() {
  // Auto-reconnect disabled: keep the UI stable after a recording ends.
}

connectBtn.addEventListener("click", connect);
clearBtn.addEventListener("click", clearEvents);
serverUrlInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    connect();
  }
});

setStatus("disconnected", "Listo para conectar al servidor.");
restoreState();
