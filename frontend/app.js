const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const messages = document.querySelector("#messages");
const clearButton = document.querySelector("#clear-button");
const connectionStatus = document.querySelector("#connection-status");
  const requestTimeoutMs = 90000;
const authPanel = document.querySelector("#auth-panel");
const authUsername = document.querySelector("#auth-username");
const authPassword = document.querySelector("#auth-password");
const authError = document.querySelector("#auth-error");
const loginButton = document.querySelector("#login-button");
const registerButton = document.querySelector("#register-button");
const logoutButton = document.querySelector("#logout-button");
const personaSelect = document.querySelector("#persona-select");
const personaNickname = document.querySelector("#persona-nickname");
const personaSave = document.querySelector("#persona-save");
const sessionStyle = document.querySelector("#session-style");
const sessionMode = document.querySelector("#session-mode");
const sessionNickname = document.querySelector("#session-nickname");
const sessionInstructions = document.querySelector("#session-instructions");
const sessionPersonaSave = document.querySelector("#session-persona-save");
const sessionPersonaReset = document.querySelector("#session-persona-reset");
const sessionPersonaStatus = document.querySelector("#session-persona-status");
const memoryPanel = document.querySelector("#memory-panel");
const memoryList = document.querySelector("#memory-list");
const memoryRefresh = document.querySelector("#memory-refresh");
const memoryButton = document.querySelector("#memory-button");
const conversationSelect = document.querySelector("#conversation-select");
const conversationTitle = document.querySelector("#conversation-title");
const conversationTitleSave = document.querySelector("#conversation-title-save");
const newConversationButton = document.querySelector("#new-conversation-button");
const deleteConversationButton = document.querySelector("#delete-conversation-button");
const forgetConversationButton = document.querySelector("#forget-conversation-button");
const tokenKey = "xiaoyu_access_token";
let currentConversationId = null;

function getToken() {
  return sessionStorage.getItem(tokenKey);
}

function formatApiError(detail) {
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object") return String(item);
      const location = Array.isArray(item.loc)
        ? item.loc.filter((part) => part !== "body").join(".")
        : "";
      const message = item.msg || "请求参数不正确";
      return location ? `${location}：${message}` : message;
    }).join("；");
  }
  if (typeof detail === "string" && detail.trim()) return detail;
  return "请求参数不正确";
}

function setLoggedIn(loggedIn) {
  authPanel.hidden = loggedIn;
  document.querySelector(".shell").hidden = !loggedIn;
}

async function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    sessionStorage.removeItem(tokenKey);
    setLoggedIn(false);
  }
  return response;
}

async function authenticate(path) {
  authError.textContent = "";
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: authUsername.value.trim(), password: authPassword.value }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiError(data.detail) || "认证失败");
  return data;
}

async function login() {
  try {
    const data = await authenticate("/auth/login");
    sessionStorage.setItem(tokenKey, data.access_token);
    setLoggedIn(true);
    await loadConversations();
    await loadHistory();
    await loadPersona();
    input.focus();
  } catch (error) {
    authError.textContent = error.message;
  }
}

async function register() {
  try {
    await authenticate("/auth/register");
    await login();
  } catch (error) {
    authError.textContent = error.message;
  }
}

async function loadHistory() {
  const query = currentConversationId ? `&conversation_id=${currentConversationId}` : "";
  const response = await apiFetch(`/chat/history?limit=200${query}`);
  if (!response.ok) return;
  const data = await response.json();
  clearConversation();
  for (const item of data.messages || []) addMessage(item.role, item.content);
}

async function loadSessionPersona() {
  if (!currentConversationId) return;
  const response = await apiFetch(`/conversations/${currentConversationId}/persona`);
  if (!response.ok) return;
  const data = await response.json();
  const overrides = data.overrides || {};
  sessionStyle.value = overrides.style_preset || "";
  sessionMode.value = overrides.conversation_mode || "";
  sessionNickname.value = overrides.nickname || "";
  sessionInstructions.value = overrides.custom_instructions || "";
  const hasOverride = Object.values(overrides).some((value) => value !== null && value !== "");
  sessionPersonaStatus.textContent = hasOverride ? "已覆盖当前会话" : "跟随默认";
}

async function saveSessionPersona(reset = false) {
  if (!currentConversationId) return;
  const body = reset
    ? { style_preset: null, conversation_mode: null, custom_instructions: null, nickname: null, relationship_level: null }
    : {
        style_preset: sessionStyle.value || null,
        conversation_mode: sessionMode.value || null,
        custom_instructions: sessionInstructions.value.trim() || null,
        nickname: sessionNickname.value.trim() || null,
        relationship_level: null,
      };
  const response = await apiFetch(`/conversations/${currentConversationId}/persona`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    setConnectionStatus("error", "会话人格保存失败");
    return;
  }
  await loadSessionPersona();
  setConnectionStatus("ready", reset ? "已恢复默认" : "会话人格已保存");
}

async function loadMemoryEvents() {
  const response = await apiFetch("/memory/events?limit=200");
  if (!response.ok) return;
  const data = await response.json();
  memoryList.replaceChildren();
  if (!data.events?.length) {
    const empty = document.createElement("p");
    empty.className = "memory-empty";
    empty.textContent = "还没有长期记忆。";
    memoryList.appendChild(empty);
    return;
  }
  for (const event of data.events) {
    const row = document.createElement("div");
    row.className = "memory-row";
    const text = document.createElement("input");
    text.value = event.event_text;
    text.maxLength = 500;
    text.setAttribute("aria-label", "记忆内容");
    const importance = document.createElement("select");
    importance.setAttribute("aria-label", "记忆重要性");
    for (const value of ["high", "mid", "low"]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value === "high" ? "重要" : value === "low" ? "较低" : "普通";
      option.selected = value === event.importance;
      importance.appendChild(option);
    }
    const save = document.createElement("button");
    save.className = "compact-button";
    save.type = "button";
    save.textContent = "保存";
    save.addEventListener("click", async () => {
      const update = await apiFetch(`/memory/events/${event.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event_text: text.value.trim(), importance: importance.value }),
      });
      setConnectionStatus(update.ok ? "ready" : "error", update.ok ? "记忆已保存" : "记忆保存失败");
      if (update.ok) await loadMemoryEvents();
    });
    const remove = document.createElement("button");
    remove.className = "compact-button danger-action";
    remove.type = "button";
    remove.textContent = "删除";
    remove.addEventListener("click", async () => {
      if (!window.confirm("确定删除这条长期记忆吗？")) return;
      const deleted = await apiFetch(`/memory/events/${event.id}`, { method: "DELETE" });
      setConnectionStatus(deleted.ok ? "ready" : "error", deleted.ok ? "记忆已删除" : "记忆删除失败");
      if (deleted.ok) await loadMemoryEvents();
    });
    row.append(text, importance, save, remove);
    memoryList.appendChild(row);
  }
}

async function loadConversations() {
  const response = await apiFetch("/conversations");
  if (!response.ok) return;
  const conversations = await response.json();
  conversationSelect.replaceChildren();
  for (const conversation of conversations) {
    const option = document.createElement("option");
    option.value = conversation.id;
    option.textContent = conversation.title;
    conversationSelect.appendChild(option);
  }
  if (conversations.length > 0) {
    const saved = Number(sessionStorage.getItem("xiaoyu_conversation_id"));
    const selected = conversations.find((item) => item.id === saved) || conversations[0];
    currentConversationId = selected.id;
    conversationSelect.value = String(selected.id);
    conversationTitle.value = selected.title;
    sessionStorage.setItem("xiaoyu_conversation_id", String(selected.id));
  } else {
    currentConversationId = null;
    conversationTitle.value = "";
  }
}

async function createConversation() {
  const response = await apiFetch("/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "新对话" }),
  });
  if (!response.ok) return;
  const conversation = await response.json();
  currentConversationId = conversation.id;
  sessionStorage.setItem("xiaoyu_conversation_id", String(conversation.id));
  await loadConversations();
  conversationSelect.value = String(conversation.id);
  conversationTitle.value = conversation.title;
  clearConversation();
  await loadSessionPersona();
}

async function renameConversation() {
  const title = conversationTitle.value.trim();
  if (!currentConversationId || !title) return;
  const response = await apiFetch(`/conversations/${currentConversationId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    setConnectionStatus("error", data.detail || "会话名称保存失败");
    return;
  }
  conversationTitle.value = data.title;
  await loadConversations();
  conversationSelect.value = String(currentConversationId);
  setConnectionStatus("ready", "会话名称已保存");
}

async function deleteConversation(forget = false) {
  if (!currentConversationId) return;
  const prompt = forget
    ? "将删除当前聊天记录，并删除能确认来自本会话的长期记忆。确定继续吗？"
    : "将删除当前聊天记录，但长期记忆会保留。确定继续吗？";
  if (!window.confirm(prompt)) return;
  const endpoint = `/conversations/${currentConversationId}${forget ? "/forget" : ""}`;
  const response = await apiFetch(endpoint, { method: "DELETE" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    setConnectionStatus("error", data.detail || "删除失败");
    return;
  }
  sessionStorage.removeItem("xiaoyu_conversation_id");
  currentConversationId = null;
  await loadConversations();
  if (!currentConversationId) {
    await createConversation();
  } else {
    await loadHistory();
  }
  setConnectionStatus(data.warnings?.length ? "error" : "ready", data.warnings?.length ? "已删除，但记忆清理有提醒" : "已删除");
}

async function loadPersona() {
  const [templatesResponse, personaResponse] = await Promise.all([
    apiFetch("/persona/templates"),
    apiFetch("/persona"),
  ]);
  if (!templatesResponse.ok || !personaResponse.ok) return;
  const templates = await templatesResponse.json();
  const persona = await personaResponse.json();
  personaSelect.replaceChildren();
  for (const template of templates) {
    const option = document.createElement("option");
    option.value = template.code;
    option.textContent = template.name;
    option.title = template.description;
    option.selected = template.code === persona.template_code;
    personaSelect.appendChild(option);
  }
  personaNickname.value = persona.nickname || "";
}

async function savePersona() {
  const response = await apiFetch("/persona", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      template_code: personaSelect.value,
      nickname: personaNickname.value.trim() || null,
      relationship_level: "close",
    }),
  });
  setConnectionStatus(response.ok ? "ready" : "error", response.ok ? "已保存" : "保存失败");
}

function addMessage(role, text, extraClass = "") {
  const welcome = messages.querySelector(".welcome");
  if (welcome) welcome.remove();
  const row = document.createElement("div");
  row.className = `message-row ${role} ${extraClass}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  row.appendChild(bubble);
  messages.appendChild(row);
  messages.scrollTop = messages.scrollHeight;
  return bubble;
}

function setConnectionStatus(state, label) {
  connectionStatus.dataset.state = state;
  connectionStatus.textContent = label;
}

function clearConversation() {
  messages.innerHTML = `
    <div class="welcome">
      <div class="welcome-mark">♡</div>
      <h2>今天想聊点什么？</h2>
      <p>把心里的话告诉我就好。</p>
    </div>`;
  setConnectionStatus("ready", "就绪");
  input.focus();
}

function addMetadata(data) {
  const details = [];
  if (data.source) details.push(`来源：${data.source}`);
  if (data.tool) details.push(`工具：${data.tool}`);
  if (details.length === 0) return;
  const lastRow = messages.lastElementChild;
  if (!lastRow) return;
  const metadata = document.createElement("small");
  metadata.className = "message-meta";
  metadata.textContent = details.join(" · ");
  lastRow.appendChild(metadata);
}

async function consumeSse(response, onDelta) {
  if (!response.body) throw new Error("浏览器不支持流式响应");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (const rawEvent of events) {
      const dataLine = rawEvent.split("\n").find((line) => line.startsWith("data: "));
      if (!dataLine) continue;
      const payload = JSON.parse(dataLine.slice(6));
      if (payload.delta) onDelta(payload.delta);
      if (payload.done) completed = true;
    }
    if (done) break;
  }
  if (!completed) throw new Error("流式响应未正常结束");
}

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
}

async function sendMessage() {
  const message = input.value.trim();
  if (!message || sendButton.disabled) return;
  addMessage("user", message);
  input.value = "";
  resizeInput();
  sendButton.disabled = true;
  input.disabled = true;
  setConnectionStatus("busy", "思考中");
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), requestTimeoutMs);
  try {
    const response = await apiFetch("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        ...(currentConversationId ? { conversation_id: currentConversationId } : {}),
      }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(formatApiError(data.detail) || "请求失败");
    }
    const assistantBubble = addMessage("assistant", "");
    await consumeSse(response, (delta) => {
      assistantBubble.textContent += delta;
      messages.scrollTop = messages.scrollHeight;
    });
    setConnectionStatus("ready", "在线");
  } catch (error) {
    const messageText = error.name === "AbortError" ? "请求超时了，请稍后再试。" : (error.message || "连接失败，请稍后再试。");
    addMessage("assistant", messageText, "error");
    setConnectionStatus("error", "连接异常");
  } finally {
    window.clearTimeout(timeout);
    sendButton.disabled = false;
    input.disabled = false;
    input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage();
});

input.addEventListener("input", resizeInput);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

clearButton.addEventListener("click", clearConversation);
newConversationButton.addEventListener("click", createConversation);
conversationTitleSave.addEventListener("click", renameConversation);
conversationTitle.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    renameConversation();
  }
});
deleteConversationButton.addEventListener("click", () => deleteConversation(false));
forgetConversationButton.addEventListener("click", () => deleteConversation(true));
conversationSelect.addEventListener("change", async () => {
  currentConversationId = Number(conversationSelect.value) || null;
  conversationTitle.value = conversationSelect.selectedOptions[0]?.textContent || "";
  if (currentConversationId) {
    sessionStorage.setItem("xiaoyu_conversation_id", String(currentConversationId));
  }
  await loadHistory();
  await loadSessionPersona();
});
loginButton.addEventListener("click", login);
registerButton.addEventListener("click", register);
logoutButton.addEventListener("click", () => {
  sessionStorage.removeItem(tokenKey);
  clearConversation();
  setLoggedIn(false);
});
personaSave.addEventListener("click", savePersona);
sessionPersonaSave.addEventListener("click", () => saveSessionPersona(false));
sessionPersonaReset.addEventListener("click", () => saveSessionPersona(true));
memoryRefresh.addEventListener("click", loadMemoryEvents);
memoryButton.addEventListener("click", async () => {
  memoryPanel.hidden = !memoryPanel.hidden;
  if (!memoryPanel.hidden) await loadMemoryEvents();
});

setLoggedIn(Boolean(getToken()));
if (getToken()) {
  loadConversations().then(async () => {
    await loadHistory();
    await loadSessionPersona();
    await loadMemoryEvents();
  });
  loadPersona();
}
