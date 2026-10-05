const transcript = document.querySelector("#transcript");
const composer = document.querySelector("#composer");
const question = document.querySelector("#question");
const send = document.querySelector("#send");
const saveKey = document.querySelector("#save-key");
const apiKey = document.querySelector("#api-key");
const chatModel = document.querySelector("#chat-model");
const keyStatus = document.querySelector("#key-status");
const statusList = document.querySelector("#status-list");
const docList = document.querySelector("#doc-list");
const fileInput = document.querySelector("#file-input");
const uploadButton = document.querySelector("#upload-button");
const uploadStatus = document.querySelector("#upload-status");
const uploadList = document.querySelector("#upload-list");
const retrievalMode = document.querySelector("#retrieval-mode");
const history = [];

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    question.value = button.dataset.prompt;
    composer.requestSubmit();
  });
});

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = question.value.trim();
  if (!message) return;
  question.value = "";
  appendMessage("user", message);
  send.disabled = true;
  const pending = appendMessage("assistant", "Searching the corpus…");
  try {
    const answer = await streamAnswer(message, pending);
    if (answer) {
      history.push({ role: "user", content: message });
      history.push({ role: "assistant", content: answer });
    }
  } catch (error) {
    pending.textContent = error.message || "The request failed.";
  } finally {
    send.disabled = false;
    question.focus();
  }
});

question.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

uploadButton.addEventListener("click", async () => {
  const files = [...fileInput.files];
  if (!files.length) {
    uploadStatus.textContent = "Choose at least one file first.";
    return;
  }
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  uploadButton.disabled = true;
  uploadStatus.textContent = "Reading the files and updating the index…";
  try {
    const response = await fetch("/api/uploads", { method: "POST", body });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Upload failed.");
    }
    fileInput.value = "";
    const saved = (payload.saved || []).join(", ");
    const problems = (payload.errors || []).join(" ");
    uploadStatus.textContent = problems
      ? `Indexed ${saved || "nothing"}. ${problems}`
      : `Indexed ${saved}. Ask a question about ${saved}.`;
    renderStatus(payload);
  } catch (error) {
    uploadStatus.textContent = error.message;
  } finally {
    uploadButton.disabled = false;
  }
});

saveKey.addEventListener("click", async () => {
  const key = apiKey.value.trim();
  if (!key) {
    keyStatus.textContent = "Paste an OpenAI API key first.";
    return;
  }
  saveKey.disabled = true;
  keyStatus.textContent = "Saving the key and embedding the corpus…";
  try {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: key, chat_model: chatModel.value }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Could not build embeddings.");
    }
    apiKey.value = "";
    keyStatus.textContent = `Embedded ${payload.embedded_chunks} chunks with ${payload.embedding_model}. The key is kept in memory for this server session.`;
    renderStatus(payload);
  } catch (error) {
    keyStatus.textContent = error.message;
  } finally {
    saveKey.disabled = false;
  }
});

async function streamAnswer(message, pending) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history }),
  });
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Chat request failed.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answer = "";
  let started = false;
  const sources = document.createElement("div");
  sources.className = "sources";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";
    for (const frame of frames) {
      const line = frame.split("\n").find((item) => item.startsWith("data:"));
      if (!line) continue;
      const event = JSON.parse(line.slice(5).trim());
      if (event.type === "sources") {
        retrievalMode.textContent = event.mode === "hybrid" ? "Hybrid: lexical + embeddings" : "Lexical search only";
        renderSources(sources, event.sources || []);
      } else if (event.type === "token") {
        if (!started) {
          pending.textContent = "";
          started = true;
        }
        answer += event.text;
        pending.textContent = answer;
        transcript.scrollTop = transcript.scrollHeight;
      } else if (event.type === "notice") {
        setProse(pending, event.text);
        if (event.footnote) {
          const note = document.createElement("p");
          note.className = "footnote";
          note.textContent = event.footnote;
          pending.appendChild(note);
        }
        answer = event.text;
      } else if (event.type === "error") {
        pending.textContent = event.text;
        throw new Error(event.text);
      }
    }
  }

  if (started && answer) {
    setProse(pending, answer);
  }
  if (sources.childElementCount) {
    pending.appendChild(sources);
  }
  pending.scrollIntoView({ block: "start" });
  return answer;
}

function setProse(element, text) {
  element.replaceChildren();
  text.split(/\n{2,}/).forEach((part) => {
    const paragraph = document.createElement("p");
    paragraph.textContent = part.trim();
    if (paragraph.textContent) element.appendChild(paragraph);
  });
}

function appendMessage(role, text) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  article.textContent = text;
  transcript.appendChild(article);
  transcript.scrollTop = transcript.scrollHeight;
  return article;
}

function renderSources(container, hits) {
  container.replaceChildren();
  if (!hits.length) return;
  const label = document.createElement("p");
  label.className = "sources-label";
  label.textContent = "Sources";
  container.appendChild(label);
  hits.slice(0, 3).forEach((hit) => {
    const block = document.createElement("div");
    block.className = "source";
    const link = document.createElement("a");
    link.href = hit.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = hit.title && hit.title !== hit.document ? `${hit.document} — ${hit.title}` : hit.document;
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Passage";
    const passage = document.createElement("p");
    passage.textContent = friendlyPassage(hit.text);
    details.append(summary, passage);
    block.append(link, details);
    container.appendChild(block);
  });
}

function friendlyPassage(text) {
  const cleaned = text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("Document:") && !line.startsWith("Source:"))
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  if (cleaned.length <= 380) return cleaned;
  return `${cleaned.slice(0, 380).replace(/\s+\S*$/, "")}…`;
}

function renderStatus(payload) {
  const rows = [
    ["Chunks", String(payload.chunks)],
    ["Lexical", payload.lexical_ready ? "Ready" : "Not built"],
    ["Embeddings", payload.embeddings_ready ? "In memory" : "Waiting for API key"],
    ["Chat model", payload.chat_model],
    ["Embedding model", payload.embedding_model],
  ];
  statusList.replaceChildren();
  rows.forEach(([label, value]) => {
    const item = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = label;
    const pill = document.createElement("span");
    const ready = value === "Ready" || value === "In memory";
    const waiting = value.startsWith("Waiting") || value === "Not built";
    pill.className = `pill${ready ? " ready" : ""}${waiting ? " wait" : ""}`;
    pill.textContent = value;
    item.append(name, pill);
    statusList.appendChild(item);
  });
  if (payload.embed_error) {
    keyStatus.textContent = payload.embed_error;
  }
  const vercelNote = document.querySelector("#vercel-note");
  if (payload.vercel) {
    vercelNote.hidden = false;
    vercelNote.textContent = "On Vercel, set OPENAI_API_KEY in the project environment variables and redeploy. A key pasted here lasts only for this running instance. Uploaded files do too. The Ranger documents stay.";
  }
  const documents = payload.documents || [];
  docList.replaceChildren();
  documents.filter((doc) => !doc.uploaded).forEach((doc) => {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = doc.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = doc.title;
    const count = document.createElement("span");
    count.className = "count";
    count.textContent = String(doc.chunks);
    item.append(link, count);
    docList.appendChild(item);
  });
  renderUploads(documents.filter((doc) => doc.uploaded));
  if (payload.has_api_key && payload.embeddings_ready) {
    apiKey.placeholder = "Key saved for this session";
  }
  if (payload.chat_model) {
    const known = [...chatModel.options].some((option) => option.value === payload.chat_model);
    if (!known) {
      const option = document.createElement("option");
      option.value = payload.chat_model;
      option.textContent = payload.chat_model;
      chatModel.appendChild(option);
    }
    chatModel.value = payload.chat_model;
  }
}

function renderUploads(documents) {
  uploadList.replaceChildren();
  if (!documents.length) {
    const empty = document.createElement("li");
    empty.textContent = "No files yet.";
    uploadList.appendChild(empty);
    return;
  }
  documents.forEach((doc) => {
    const item = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = doc.upload_name || doc.title;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove-doc";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => removeUpload(doc.upload_name));
    item.append(name, remove);
    uploadList.appendChild(item);
  });
}

async function removeUpload(filename) {
  uploadStatus.textContent = `Removing ${filename}…`;
  const response = await fetch(`/api/uploads/${encodeURIComponent(filename)}`, { method: "DELETE" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    uploadStatus.textContent = payload.detail || "Could not remove that file.";
    return;
  }
  uploadStatus.textContent = `Removed ${filename}.`;
  renderStatus(payload);
}

async function refreshStatus() {
  const response = await fetch("/api/status");
  if (!response.ok) return;
  renderStatus(await response.json());
}

refreshStatus();
