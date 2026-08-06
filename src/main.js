import { invoke } from "@tauri-apps/api/core";
import "./styles/tailwind.css";

const button = document.querySelector("#health-button");
const statusBadge = document.querySelector("#status-badge");
const statusLabel = document.querySelector("#status-label");
const healthSummary = document.querySelector("#health-summary");
const healthDetails = document.querySelector("#health-details");
const completionMark = document.querySelector("#completion-mark");
const errorMessage = document.querySelector("#error-message");

const environmentLabels = [
  ["python_available", "Python"],
  ["pymupdf4llm_available", "PyMuPDF4LLM"],
  ["pandoc_available", "Pandoc"],
  ["git_cli_available", "Git"],
  ["github_cli_available", "GitHub CLI"],
];

function setStatus(state, label) {
  statusBadge.dataset.state = state;
  statusLabel.textContent = label;
}

function renderHealth(health) {
  const environment = health.local_environment ?? {};
  const availableCount = environmentLabels.reduce(
    (count, [key]) => count + (environment[key] ? 1 : 0),
    0,
  );

  healthDetails.replaceChildren(
    ...environmentLabels.map(([key, label]) => {
      const row = document.createElement("div");
      row.className = "health-row";
      const name = document.createElement("dt");
      name.textContent = label;
      const value = document.createElement("dd");
      value.className = environment[key] ? "health-value is-ready" : "health-value is-missing";
      value.textContent = environment[key] ? "Available" : "Unavailable";
      row.append(name, value);
      return row;
    }),
  );

  const healthy = health.status === "ok";
  setStatus(healthy ? "success" : "warning", healthy ? "Ready" : "Review");
  healthSummary.textContent = `${availableCount}/${environmentLabels.length} local dependencies available.`;
  completionMark.classList.remove("is-visible");
  requestAnimationFrame(() => completionMark.classList.add("is-visible"));
}

async function checkEnvironment() {
  button.disabled = true;
  button.classList.add("is-loading");
  setStatus("working", "Checking");
  healthSummary.textContent = "Probing the local environment…";
  errorMessage.textContent = "";

  try {
    const health = await invoke("check_system_health");
    renderHealth(health);
  } catch (error) {
    setStatus("error", "Unavailable");
    healthSummary.textContent = "The native healthcheck could not be reached.";
    errorMessage.textContent = error instanceof Error ? error.message : String(error);
  } finally {
    button.disabled = false;
    button.classList.remove("is-loading");
  }
}

button.addEventListener("click", checkEnvironment);

if (window.__TAURI_INTERNALS__) {
  checkEnvironment();
} else {
  setStatus("idle", "Preview");
  healthSummary.textContent = "Open the desktop build to run the native probe.";
}
