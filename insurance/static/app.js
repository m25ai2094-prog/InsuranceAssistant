"use strict";

const el = id => document.getElementById(id);
const input = el("input");
const messages = el("messages");
const services = {
  register: ["Register a claim", "Record an incident and review your documents.", "+", "claims"],
  track: ["Track a claim", "Check where a recorded claim stands.", "→", "claims"],
  checklist: ["Claim document checklist", "See what to prepare for an incident.", "≡", "claims"],
  advice: ["Recommend a policy", "Compare sample plans by cover and budget.", "◇", "coverage"],
  policy: ["View my policy", "Look up cover and policy dates.", "▤", "coverage"],
  premium: ["Check premium due", "Find your renewal date and premium.", "₹", "coverage"],
  support: ["Talk to a person", "Add a request to the demo support queue.", "?", "coverage"],
};

const flowNames = {
  claim_intimation: "Register a claim", claim_status: "Track a claim",
  document_checklist: "Claim document checklist", insurance_advisory: "Compare plans",
  policy_details: "View my policy", premium_due: "Check premium due", human_handoff: "Get support",
};
const stages = {
  verify: ["Verify policy", ["policy_number", "mobile", "otp"]],
  details: ["Incident details", ["claim_type", "incident_date", "description", "provider"]],
  docs: ["Document readiness", ["documents"]],
  review: ["Review and submit", ["confirmation"]],
  reference: ["Enter claim reference", ["claim_reference"]],
  type: ["Choose insurance type", ["category"]],
  match: ["Set eligibility and budget", ["age", "coverage", "budget"]],
  incident: ["Choose incident type", ["checklist_type"]],
  topic: ["Choose a topic", ["support_topic"]],
};
const progress = {
  claim_intimation: ["verify", "details", "docs", "review"], claim_status: ["verify", "reference"],
  document_checklist: ["type", "incident"], insurance_advisory: ["type", "match"],
  policy_details: ["verify"], premium_due: ["verify"], human_handoff: ["topic"],
};
const steps = {
  menu: "Choose a service", category: "Insurance type", age: "Age",
  coverage: "Minimum cover", budget: "Monthly budget", checklist_type: "Claim type",
  policy_number: "Policy number", mobile: "Demo mobile", otp: "Verification code",
  claim_reference: "Claim reference", claim_type: "Claim type", incident_date: "Incident date",
  description: "Incident description", provider: "Facility", documents: "Document readiness",
  confirmation: "Review and confirm", support_topic: "Support topic",
};
const hints = {
  policy_number: "e.g. POL-HLT-1001", mobile: "10-digit demo mobile", otp: "6-digit demo code",
  age: "e.g. 30", coverage: "e.g. 5", budget: "e.g. 1200", claim_reference: "e.g. CLM-0000001001",
  incident_date: "YYYY-MM-DD", documents: "Or type item numbers, e.g. 1, 3",
};
const masked = new Set(["policy_number", "mobile", "otp", "claim_reference", "description", "provider"]);
const numeric = new Set(["age", "coverage", "budget", "mobile", "otp"]);
const recordFields = {policy_number: "policy", mobile: "mobile", incident_date: "incident_date", claim_reference: "claim"};
const recordLabels = {policy: "Policy number", mobile: "Demo mobile", incident_date: "Sample date", claim: "Seed claim reference"};
const results = new Set(["claim_registered", "claim_status_complete", "policy_complete", "premium_complete",
  "advisory_complete", "advisory_no_match", "checklist_complete", "handoff_queued"]);
const viewTitles = {overview: "Overview", claims: "Claim centre", assistant: "Assistant"};
const state = {
  view: "overview", records: [], reply: null, ready: false, busy: false, failure: null,
  replacement: null, latestClaim: "", inboxCode: "", inboxTimer: null, inboxVersion: 0,
};

function tag(name, css, text) {
  const node = document.createElement(name);
  if (css) node.className = css;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(text, css, action) {
  const node = tag("button", `button ${css}`, text);
  node.type = "button";
  if (action) node.addEventListener("click", action);
  return node;
}

async function api(path, method = "GET", body) {
  const response = await fetch(path, {
    method, credentials: "same-origin",
    headers: body ? {"Content-Type": "application/json"} : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || "The local assistant is unavailable.");
    error.status = response.status;
    throw error;
  }
  return data;
}

function setBusy(busy) {
  state.busy = busy;
  const disabled = busy || !state.ready;
  for (const node of document.querySelectorAll(
    "[data-service], #composer input, #composer button, #choices button, #records button, #records select, " +
    "#code, #reset, #replace-request, #document-form input, #review-claim, #retry",
  )) node.disabled = disabled;
  el("reconnect").disabled = busy;
}

function composeNote(text = "", error = false) {
  const note = el("compose-note");
  note.textContent = text;
  note.classList.toggle("error", error);
}

function showView(name, focus = true) {
  state.view = name;
  el("current-view").textContent = viewTitles[name];
  for (const key of Object.keys(viewTitles)) el(`${key}-view`).hidden = key !== name;
  for (const item of document.querySelectorAll("nav [data-view]")) {
    if (item.dataset.view === name) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  if (name === "assistant") scrollMessages();
  if (focus) el(`${name}-title`).focus();
}

function buildTiles() {
  for (const group of document.querySelectorAll("[data-cards]")) {
    for (const key of group.dataset.cards.split(" ")) {
      const [name, summary, symbol, kind] = services[key];
      const tile = tag("button", "tile");
      tile.type = "button";
      tile.dataset.service = key;
      tile.dataset.kind = kind;
      tile.setAttribute("aria-label", name);
      const icon = tag("span", "tile-icon", symbol);
      icon.setAttribute("aria-hidden", "true");
      const copy = tag("span");
      copy.append(tag("strong", "", name), tag("small", "", summary));
      const arrow = tag("span", "arrow", "→");
      arrow.setAttribute("aria-hidden", "true");
      tile.append(icon, copy, arrow);
      group.append(tile);
    }
  }
}

function appendPairs(target, rows) {
  const pairs = tag("dl");
  for (const [label, value] of rows) {
    const pair = tag("div");
    pair.append(tag("dt", "", label), tag("dd", "", value));
    pairs.append(pair);
  }
  target.append(pairs);
}

function appendList(target, items, heading) {
  if (heading) target.append(tag("p", "missing", heading));
  const list = tag("ul", "document-list");
  for (const item of items) list.append(tag("li", "", item));
  target.append(list);
}

function appendMessage(role, text, reply = {}) {
  const message = tag("div", `message ${role}`);
  message.append(tag("span", "message-name", role === "user" ? "You" : "Assistant"));
  const bubble = tag("div", "bubble");
  bubble.append(tag("p", "", text));
  if (reply.card && reply.step !== "confirmation") {
    const result = tag("div", reply.card.tone === "success" ? "result success" : "result");
    result.append(tag("h3", "", reply.card.title));
    appendPairs(result, reply.card.rows);
    bubble.append(result);
  }
  if (reply.items?.length && !["documents", "confirmation"].includes(reply.step)) {
    appendList(bubble, reply.items, ["claim_registered", "claim_status_complete"].includes(reply.event)
      ? "Documents still required" : "");
  }
  message.append(bubble);
  messages.append(message);
}

function scrollMessages() {
  messages.scrollTop = messages.scrollHeight;
}

function renderProgress(reply) {
  const finished = results.has(reply.event);
  const flow = reply.flow !== "menu" ? reply.flow : finished ? reply.trace[0]?.flow : "";
  const name = flowNames[flow];
  el("request-name").textContent = name || "Choose a service to begin.";
  const list = el("request-progress");
  list.replaceChildren();
  const ordered = progress[flow] || [];
  const current = ordered.findIndex(key => stages[key][1].includes(reply.step));
  for (const [index, key] of ordered.entries()) {
    const done = finished || (current !== -1 && index < current);
    const node = tag("li", done ? "progress-step done" : "progress-step");
    const indicator = tag("span", "", done ? "✓" : String(index + 1));
    indicator.setAttribute("aria-hidden", "true");
    if (!finished && index === current) node.setAttribute("aria-current", "step");
    if (done) node.setAttribute("aria-label", `${stages[key][0]}, complete`);
    node.append(indicator, document.createTextNode(stages[key][0]));
    list.append(node);
  }
  for (const banner of document.querySelectorAll("[data-resume]")) {
    banner.hidden = reply.step === "menu";
    banner.querySelector("[data-resume-name]").textContent = name || "Continue in the assistant.";
  }
}

function renderTrace(reply) {
  const model = reply.last_model;
  const lightweight = model?.source === "lightweight_rules";
  const confidence = model?.confidence == null ? "" : lightweight
    ? ` · heuristic score ${Math.round(model.confidence * 100)}%`
    : ` · ${Math.round(model.confidence * 100)}%`;
  const engine = lightweight ? "RULE-BASED" : "DIET";
  el("model-intent").textContent = model ? `${engine} · ${model.intent.replaceAll("_", " ")}${confidence}` : "Awaiting a request";
  const trace = el("trace-list");
  trace.replaceChildren();
  for (const entry of reply.trace.slice(0, 3)) {
    const row = tag("li");
    row.append(tag("span", "", entry.event.replaceAll("_", " ")), tag("span", "", `${entry.server_ms.toFixed(1)} ms`));
    trace.append(row);
  }
}

function renderRecords() {
  const key = recordFields[state.reply?.step];
  const selected = state.records[Number(el("record-select").value)];
  const view = el("records");
  const values = el("record-values");
  values.replaceChildren();
  view.hidden = !key || !selected;
  if (view.hidden) return;

  function add(label, text) {
    const row = tag("div", "record-row");
    const value = tag("dd");
    const use = button(text, "quiet", () => submit(text));
    use.setAttribute("aria-label", `Use ${label.toLowerCase()} ${text}`);
    value.append(use);
    row.append(tag("dt", "", label), value);
    values.append(row);
  }

  if (selected[key]) add(recordLabels[key], selected[key]);
  if (key === "claim" && state.latestClaim) add("Last claim reference", state.latestClaim);
  if (!values.childElementCount) {
    const row = tag("div", "record-row");
    row.append(tag("dt", "", "Reference"), tag("dd", "", "Use a receipt for this policy."));
    values.append(row);
  }
}

function renderDocumentForm(reply, preserve) {
  const form = el("document-form");
  const fieldset = el("document-options");
  form.hidden = reply.step !== "documents";
  if (form.hidden || !reply.items.length) return;
  const current = preserve ? new Set(Array.from(fieldset.querySelectorAll(":checked"), field => field.value)) : new Set();
  fieldset.replaceChildren(tag("legend", "", "Select the documents you have"));
  for (const [index, item] of reply.items.entries()) {
    const label = tag("label", "doc-choice");
    const field = tag("input");
    field.type = "checkbox";
    field.value = String(index + 1);
    field.checked = current.has(field.value);
    label.append(field, tag("span", "", item.replace(/^\d+\.\s*/, "")));
    fieldset.append(label);
  }
}

function renderReview(reply) {
  const review = el("review");
  review.replaceChildren();
  review.hidden = reply.step !== "confirmation" || !reply.card;
  if (review.hidden) return;
  review.append(tag("h3", "", reply.card.title));
  appendPairs(review, reply.card.rows);
  if (reply.items.length) appendList(review, reply.items, "Documents still required");
}

function renderChoices(reply) {
  const choices = el("choices");
  choices.replaceChildren();
  if (reply.event === "claim_registered") {
    choices.append(button("Track this claim", "primary", () => beginService("track")));
  }
  const options = reply.step === "documents" ? [] : [...reply.options];
  if (reply.step !== "menu" && !options.includes("Cancel")) options.push("Cancel");
  for (const option of options) {
    choices.append(button(option, option === "Confirm claim" ? "primary" : "quiet", () => submit(option)));
  }
}

function applyReply(reply) {
  const preserve = state.reply?.step === "documents";
  state.reply = reply;
  if (reply.event === "claim_registered") state.latestClaim = reply.card.title;
  const step = reply.step;
  el("current-step").textContent = steps[step] || steps.menu;
  input.placeholder = hints[step] || "Type an insurance request";
  input.type = ["mobile", "otp"].includes(step) ? "password" : "text";
  input.inputMode = numeric.has(step) ? "numeric" : "text";
  renderProgress(reply);
  renderTrace(reply);
  renderRecords();
  renderDocumentForm(reply, preserve);
  renderReview(reply);
  renderChoices(reply);
  composeNote(masked.has(step) ? "This entry is masked in the conversation." : "");
  scrollMessages();
  refreshInbox();
}

async function refreshInbox() {
  const version = ++state.inboxVersion;
  clearTimeout(state.inboxTimer);
  const inbox = el("inbox");
  const code = el("code");
  inbox.hidden = state.reply?.step !== "otp";
  code.hidden = true;
  state.inboxCode = "";
  if (inbox.hidden) return;
  const notice = el("inbox-message");
  notice.textContent = "Checking for the current demo code…";
  try {
    const result = await api("/api/demo-inbox");
    if (version !== state.inboxVersion) return;
    if (!result.code) {
      notice.textContent = "No active code. Check the sample record or choose Resend code.";
      return;
    }
    state.inboxCode = result.code;
    notice.textContent = "Use the code to verify this demo policy.";
    code.textContent = `Use code ${result.code}`;
    code.setAttribute("aria-label", "Use the demo verification code");
    code.hidden = false;
    state.inboxTimer = setTimeout(refreshInbox, (result.expires_in + 1) * 1000);
  } catch {
    if (version === state.inboxVersion) notice.textContent = "Inbox unavailable. Choose Resend code to retry.";
  }
}

function showSession(data) {
  const select = el("record-select");
  const oldIndex = Number(select.value);
  state.records = data.demo_records;
  select.replaceChildren();
  for (const [index, record] of state.records.entries()) {
    const option = tag("option", "", `${record.category} insurance`);
    option.value = String(index);
    select.append(option);
  }
  if (state.records[oldIndex]) select.value = String(oldIndex);
  state.ready = true;
  state.reply = null;
  messages.replaceChildren();
  appendMessage("assistant", data.message.text, data.message);
  applyReply(data.message);
}

function dismissSwitch() {
  state.replacement = null;
  el("switch-request").hidden = true;
}

async function submit(value) {
  const text = value.trim();
  if (!text || state.busy || !state.ready) return;
  dismissSwitch();
  const requestId = state.failure?.text === text ? state.failure.requestId : crypto.randomUUID();
  el("retry").hidden = true;
  setBusy(true);
  composeNote("Waiting for the assistant…");
  try {
    const reply = await api("/api/chat", "POST", {text, request_id: requestId});
    state.failure = null;
    input.value = "";
    appendMessage("user", reply.echo);
    appendMessage("assistant", reply.text, reply);
    applyReply(reply);
  } catch (error) {
    state.failure = {text, requestId};
    el("retry").hidden = error.status === 401;
    composeNote(error.status === 401 ? "This demo session has expired. Choose New session." : error.message, true);
  } finally {
    setBusy(false);
    if (state.view === "assistant" && el("retry").hidden) input.focus({preventScroll: true});
  }
}

function beginService(key) {
  if (state.busy || !state.ready) return;
  showView("assistant");
  if (state.reply.step !== "menu") {
    state.replacement = key;
    el("switch-message").textContent = `Discard the current request and start “${services[key][0]}”?`;
    el("switch-request").hidden = false;
    el("keep-request").focus();
    return;
  }
  submit(services[key][0]);
}

async function resetSession(nextService = null) {
  if (state.busy) return;
  dismissSwitch();
  setBusy(true);
  let switched = false;
  try {
    let session;
    try {
      session = await api("/api/reset", "POST");
    } catch (error) {
      if (error.status !== 401) throw error;
      session = await api("/api/session");
    }
    state.latestClaim = "";
    state.failure = null;
    el("retry").hidden = true;
    input.value = "";
    showSession(session);
    switched = true;
  } catch (error) {
    composeNote(error.message, true);
  } finally {
    setBusy(false);
  }
  if (switched && nextService) beginService(nextService);
  else input.focus({preventScroll: true});
}

async function initialize() {
  setBusy(true);
  el("startup").hidden = true;
  try {
    showSession(await api("/api/session"));
    if (state.reply.step !== "menu") showView("assistant", false);
  } catch {
    el("startup-message").textContent = "Could not open the demo session. Check the local server and reconnect.";
    el("startup").hidden = false;
  } finally {
    setBusy(false);
  }
  try {
    await api("/api/health");
    el("health").dataset.state = "ready";
    el("health-text").textContent = "Local demo ready";
  } catch {
    el("health").dataset.state = "unavailable";
    el("health-text").textContent = "Rasa unavailable";
  }
}

buildTiles();
document.addEventListener("click", event => {
  const nav = event.target.closest("button[data-view]");
  if (nav) { dismissSwitch(); showView(nav.dataset.view); }
  const service = event.target.closest("button[data-service]");
  if (service) beginService(service.dataset.service);
});
el("record-select").addEventListener("change", renderRecords);
el("code").addEventListener("click", () => submit(state.inboxCode));
el("retry").addEventListener("click", () => { if (state.failure) submit(state.failure.text); });
el("keep-request").addEventListener("click", () => { dismissSwitch(); input.focus({preventScroll: true}); });
el("replace-request").addEventListener("click", () => resetSession(state.replacement));
el("reset").addEventListener("click", () => resetSession());
el("reconnect").addEventListener("click", initialize);
el("composer").addEventListener("submit", event => { event.preventDefault(); submit(input.value); });
el("document-form").addEventListener("submit", event => {
  event.preventDefault();
  const chosen = Array.from(el("document-options").querySelectorAll(":checked"), field => field.value);
  submit(chosen.length ? chosen.join(", ") : "None ready");
});

initialize();
