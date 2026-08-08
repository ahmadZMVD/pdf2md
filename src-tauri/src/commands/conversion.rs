//! Sequential document conversion queue and Tauri IPC commands.
//!
//! The GUI never waits for a child process: `start_conversion_batch` prepares
//! the immutable queue snapshot and starts one named worker thread.  That
//! worker owns exactly one subprocess at a time, drops its output buffers after
//! each document, and records terminal errors instead of propagating a panic.

use crate::commands::tools::resolve_tool;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{
    atomic::{AtomicBool, AtomicU64, Ordering},
    Arc, Mutex,
};
use tauri::Manager;

const SUPPORTED_EXTENSIONS: &[&str] = &["pdf", "docx", "txt"];
const MAX_ERROR_LENGTH: usize = 1_000;

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BatchRequest {
    pub files: Vec<String>,
    pub output_directory: String,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum QueueItemStatus {
    Queued,
    Processing,
    Completed,
    Failed,
    Unsupported,
    Cancelled,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum BatchStatus {
    Idle,
    Running,
    Completed,
    Cancelled,
    Failed,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct QueueItem {
    pub source_path: String,
    pub output_path: Option<String>,
    pub status: QueueItemStatus,
    pub error: Option<String>,
    pub characters: Option<usize>,
    pub elapsed_seconds: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct QueueSnapshot {
    pub batch_id: u64,
    pub status: BatchStatus,
    pub total: usize,
    pub completed: usize,
    pub cancel_requested: bool,
    pub items: Vec<QueueItem>,
}

impl Default for QueueSnapshot {
    fn default() -> Self {
        Self {
            batch_id: 0,
            status: BatchStatus::Idle,
            total: 0,
            completed: 0,
            cancel_requested: false,
            items: Vec::new(),
        }
    }
}

/// Application state managed by Tauri.  Its mutex is held only while a small
/// status snapshot is read or changed; no filesystem or subprocess work occurs
/// under the lock.
#[derive(Clone)]
pub struct ConversionQueue {
    snapshot: Arc<Mutex<QueueSnapshot>>,
    cancellation: Arc<AtomicBool>,
    next_batch_id: Arc<AtomicU64>,
}

impl Default for ConversionQueue {
    fn default() -> Self {
        Self {
            snapshot: Arc::new(Mutex::new(QueueSnapshot::default())),
            cancellation: Arc::new(AtomicBool::new(false)),
            next_batch_id: Arc::new(AtomicU64::new(0)),
        }
    }
}

#[derive(Debug)]
struct WorkResult {
    status: QueueItemStatus,
    error: Option<String>,
    characters: Option<usize>,
    elapsed_seconds: Option<f64>,
}

impl WorkResult {
    fn completed(characters: usize, elapsed_seconds: Option<f64>) -> Self {
        Self {
            status: QueueItemStatus::Completed,
            error: None,
            characters: Some(characters),
            elapsed_seconds,
        }
    }

    fn failed(error: impl Into<String>) -> Self {
        Self {
            status: QueueItemStatus::Failed,
            error: Some(truncate_error(error.into())),
            characters: None,
            elapsed_seconds: None,
        }
    }

    fn unsupported(extension: &str) -> Self {
        Self {
            status: QueueItemStatus::Unsupported,
            error: Some(format!("unsupported format: .{extension}")),
            characters: None,
            elapsed_seconds: None,
        }
    }
}

fn lock_snapshot(queue: &Arc<Mutex<QueueSnapshot>>) -> std::sync::MutexGuard<'_, QueueSnapshot> {
    // A conversion worker never intentionally panics. If an embedding host
    // poisoned the mutex, retaining the last consistent snapshot is safer than
    // crashing the desktop application during status polling.
    queue.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn extension_of(path: &Path) -> String {
    path.extension()
        .and_then(|extension| extension.to_str())
        .unwrap_or_default()
        .trim()
        .to_ascii_lowercase()
}

fn supported(extension: &str) -> bool {
    SUPPORTED_EXTENSIONS.contains(&extension)
}

fn sanitize_stem(stem: &str) -> String {
    let cleaned = stem
        .chars()
        .filter(|character| !character.is_control() && !matches!(character, '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*'))
        .collect::<String>()
        .trim_matches([' ', '.'])
        .to_owned();
    let reserved = ["CON", "PRN", "AUX", "NUL"];
    let upper = cleaned.to_ascii_uppercase();
    let numbered_device = ["COM", "LPT"].iter().any(|prefix| {
        upper
            .strip_prefix(prefix)
            .is_some_and(|suffix| suffix.len() == 1 && matches!(suffix.as_bytes()[0], b'1'..=b'9'))
    });
    if cleaned.is_empty()
        || reserved.iter().any(|value| cleaned.eq_ignore_ascii_case(value))
        || numbered_device
    {
        "document".to_owned()
    } else {
        cleaned
    }
}

fn output_path_for(source: &Path, output_dir: &Path, reserved: &mut HashSet<String>) -> PathBuf {
    let raw_stem = source.file_stem().and_then(|value| value.to_str()).unwrap_or("document");
    let stem = sanitize_stem(raw_stem);
    let mut number = 0usize;
    loop {
        let suffix = if number == 0 { String::new() } else { format!("_{number}") };
        let candidate = output_dir.join(format!("{stem}{suffix}.md"));
        let key = candidate.to_string_lossy().to_ascii_lowercase();
        if !candidate.exists() && !reserved.contains(&key) {
            reserved.insert(key);
            return candidate;
        }
        number += 1;
    }
}

fn truncate_error(message: String) -> String {
    let trimmed = message.trim();
    if trimmed.chars().count() <= MAX_ERROR_LENGTH {
        return trimmed.to_owned();
    }
    let prefix: String = trimmed.chars().take(MAX_ERROR_LENGTH - 1).collect();
    format!("{prefix}…")
}

fn script_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join("scripts").join("pdf_engine.py"));
        candidates.push(resource_dir.join("pdf_engine.py"));
    }
    if let Ok(current_dir) = std::env::current_dir() {
        candidates.push(current_dir.join("scripts").join("pdf_engine.py"));
    }
    if let Ok(executable) = std::env::current_exe() {
        if let Some(parent) = executable.parent() {
            candidates.push(parent.join("resources").join("scripts").join("pdf_engine.py"));
        }
    }
    candidates.into_iter().find(|candidate| candidate.is_file())
}

fn json_error(output: &[u8], fallback: &str) -> String {
    serde_json::from_slice::<Value>(output)
        .ok()
        .and_then(|value| value.get("error").and_then(Value::as_str).map(str::to_owned))
        .filter(|message| !message.trim().is_empty())
        .unwrap_or_else(|| fallback.to_owned())
}

fn process_pdf(source: &Path, output: &Path, engine_script: Option<&Path>) -> WorkResult {
    let Some(engine_script) = engine_script else {
        return WorkResult::failed("PDF engine script is unavailable in application resources");
    };
    let python = resolve_tool("python");
    let Some(python_path) = python.path else {
        return WorkResult::failed("Python runtime is unavailable; install Python or bundle it in resources/bin");
    };

    let command = Command::new(python_path)
        .args(["-X", "utf8", "-I"])
        .arg(engine_script)
        .arg("--input")
        .arg(source)
        .arg("--output")
        .arg(output)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output();
    let output_result = match command {
        Ok(result) => result,
        Err(error) => return WorkResult::failed(format!("could not start Python PDF engine: {error}")),
    };

    let fallback = String::from_utf8_lossy(&output_result.stderr).trim().to_owned();
    if !output_result.status.success() {
        return WorkResult::failed(json_error(&output_result.stdout, &fallback));
    }
    let payload: Value = match serde_json::from_slice(&output_result.stdout) {
        Ok(payload) => payload,
        Err(error) => return WorkResult::failed(format!("PDF engine returned invalid JSON: {error}")),
    };
    if payload.get("status").and_then(Value::as_str) != Some("success") {
        return WorkResult::failed(json_error(&output_result.stdout, "PDF engine did not report success"));
    }
    let characters = payload
        .get("characters")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .unwrap_or_default();
    let elapsed_seconds = payload.get("elapsed_seconds").and_then(Value::as_f64);
    WorkResult::completed(characters, elapsed_seconds)
}

fn process_pandoc(source: &Path, output: &Path, extension: &str) -> WorkResult {
    let pandoc = resolve_tool("pandoc");
    let Some(pandoc_path) = pandoc.path else {
        return WorkResult::failed("Pandoc is unavailable; install Pandoc or bundle it in resources/bin");
    };
    let input_format = if extension == "docx" { "docx" } else { "markdown" };
    let started = std::time::Instant::now();
    let result = Command::new(pandoc_path)
        .arg(format!("--from={input_format}"))
        .arg("--to=gfm")
        .arg("--output")
        .arg(output)
        .arg(source)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .output();
    let process = match result {
        Ok(result) => result,
        Err(error) => return WorkResult::failed(format!("could not start Pandoc: {error}")),
    };
    if !process.status.success() {
        return WorkResult::failed(String::from_utf8_lossy(&process.stderr).to_string());
    }
    let markdown = match fs::read_to_string(output) {
        Ok(markdown) => preserve_math_notation(markdown),
        Err(error) => return WorkResult::failed(format!("Pandoc reported success but output was unavailable: {error}")),
    };
    if let Err(error) = fs::write(output, &markdown) {
        return WorkResult::failed(format!("could not finalize Pandoc output: {error}"));
    }
    let characters = markdown.chars().count();
    WorkResult::completed(characters, Some(started.elapsed().as_secs_f64()))
}

/// Pandoc's strict GFM writer wraps TeX in inline code and fenced `math`
/// blocks. GitHub accepts dollar math, and restoring those delimiters retains
/// the source formula notation requested by the conversion contract.
fn preserve_math_notation(markdown: String) -> String {
    let inline = markdown.replace("$`", "$").replace("`$", "$");
    let mut output = String::with_capacity(inline.len());
    let mut in_math_fence = false;
    for line in inline.split_inclusive('\n') {
        let trimmed = line.trim();
        if trimmed == "``` math" {
            output.push_str("$$\n");
            in_math_fence = true;
        } else if in_math_fence && trimmed == "```" {
            output.push_str("$$\n");
            in_math_fence = false;
        } else {
            output.push_str(line);
        }
    }
    if in_math_fence {
        output.push_str("$$\n");
    }
    output
}

fn process_item(source: &Path, output: Option<&Path>, engine_script: Option<&Path>) -> WorkResult {
    let extension = extension_of(source);
    if !supported(&extension) {
        return WorkResult::unsupported(&extension);
    }
    let Some(output) = output else {
        return WorkResult::failed("queue item is missing its output path");
    };
    match extension.as_str() {
        "pdf" => process_pdf(source, output, engine_script),
        "docx" | "txt" => process_pandoc(source, output, &extension),
        _ => WorkResult::unsupported(&extension),
    }
}

fn mark_result(snapshot: &mut QueueSnapshot, index: usize, result: WorkResult) {
    if let Some(item) = snapshot.items.get_mut(index) {
        item.status = result.status;
        item.error = result.error;
        item.characters = result.characters;
        item.elapsed_seconds = result.elapsed_seconds;
        snapshot.completed += 1;
    }
}

fn run_worker(
    queue: Arc<Mutex<QueueSnapshot>>,
    cancellation: Arc<AtomicBool>,
    engine_script: Option<PathBuf>,
) {
    loop {
        if cancellation.load(Ordering::Acquire) {
            break;
        }
        let next = {
            let mut snapshot = lock_snapshot(&queue);
            let Some(index) = snapshot.items.iter().position(|item| item.status == QueueItemStatus::Queued) else {
                break;
            };
            let item = &mut snapshot.items[index];
            item.status = QueueItemStatus::Processing;
            (
                index,
                PathBuf::from(&item.source_path),
                item.output_path.as_ref().map(PathBuf::from),
            )
        };

        let result = process_item(&next.1, next.2.as_deref(), engine_script.as_deref());
        let mut snapshot = lock_snapshot(&queue);
        mark_result(&mut snapshot, next.0, result);
    }

    let mut snapshot = lock_snapshot(&queue);
    if cancellation.load(Ordering::Acquire) || snapshot.cancel_requested {
        let mut cancelled = 0usize;
        for item in snapshot.items.iter_mut() {
            if item.status == QueueItemStatus::Queued {
                item.status = QueueItemStatus::Cancelled;
                cancelled += 1;
            }
        }
        snapshot.completed += cancelled;
        snapshot.status = BatchStatus::Cancelled;
    } else {
        snapshot.status = BatchStatus::Completed;
    }
}

fn fail_start(snapshot: &mut QueueSnapshot, message: &str) {
    let mut failed = 0usize;
    for item in snapshot.items.iter_mut() {
        if item.status == QueueItemStatus::Queued {
            item.status = QueueItemStatus::Failed;
            item.error = Some(message.to_owned());
            failed += 1;
        }
    }
    snapshot.completed += failed;
    snapshot.status = BatchStatus::Failed;
}

/// Start a batch.  A second active batch is rejected instead of introducing
/// races over output names or process memory.
#[tauri::command]
pub fn start_conversion_batch(
    request: BatchRequest,
    state: tauri::State<'_, ConversionQueue>,
    app: tauri::AppHandle,
) -> Result<QueueSnapshot, String> {
    if request.files.is_empty() {
        return Err("select at least one document before starting conversion".to_owned());
    }
    if request.output_directory.trim().is_empty() {
        return Err("select an output directory before starting conversion".to_owned());
    }

    let output_directory = PathBuf::from(&request.output_directory);
    fs::create_dir_all(&output_directory)
        .map_err(|error| format!("cannot create output directory: {error}"))?;
    let mut reserved = HashSet::new();
    let mut items = Vec::with_capacity(request.files.len());
    for source_path in request.files {
        let source = PathBuf::from(&source_path);
        let extension = extension_of(&source);
        let output_path = if supported(&extension) {
            Some(output_path_for(&source, &output_directory, &mut reserved).to_string_lossy().into_owned())
        } else {
            None
        };
        items.push(QueueItem {
            source_path,
            output_path,
            status: QueueItemStatus::Queued,
            error: None,
            characters: None,
            elapsed_seconds: None,
        });
    }

    let queue = state.snapshot.clone();
    let cancellation = state.cancellation.clone();
    let initial_snapshot = {
        let mut snapshot = lock_snapshot(&queue);
        if snapshot.status == BatchStatus::Running {
            return Err("a conversion batch is already running".to_owned());
        }
        cancellation.store(false, Ordering::Release);
        *snapshot = QueueSnapshot {
            batch_id: state.next_batch_id.fetch_add(1, Ordering::Relaxed) + 1,
            status: BatchStatus::Running,
            total: items.len(),
            completed: 0,
            cancel_requested: false,
            items,
        };
        snapshot.clone()
    };

    let engine_script = script_path(&app);
    let worker_queue = queue.clone();
    let worker_cancellation = cancellation.clone();
    if let Err(error) = std::thread::Builder::new()
        .name("pdf2md-conversion-queue".to_owned())
        .spawn(move || run_worker(worker_queue, worker_cancellation, engine_script))
    {
        let mut snapshot = lock_snapshot(&queue);
        fail_start(&mut snapshot, "unable to start conversion worker");
        return Err(format!("unable to start conversion worker: {error}"));
    }
    Ok(initial_snapshot)
}

/// Request cancellation. The active child process is allowed to finish safely;
/// all queued files are immediately marked cancelled and will never be started.
#[tauri::command]
pub fn cancel_batch(state: tauri::State<'_, ConversionQueue>) -> QueueSnapshot {
    state.cancellation.store(true, Ordering::Release);
    let mut snapshot = lock_snapshot(&state.snapshot);
    if snapshot.status == BatchStatus::Running {
        snapshot.cancel_requested = true;
        let mut cancelled = 0usize;
        for item in snapshot.items.iter_mut() {
            if item.status == QueueItemStatus::Queued {
                item.status = QueueItemStatus::Cancelled;
                cancelled += 1;
            }
        }
        snapshot.completed += cancelled;
    }
    snapshot.clone()
}

#[tauri::command]
pub fn get_queue_status(state: tauri::State<'_, ConversionQueue>) -> QueueSnapshot {
    lock_snapshot(&state.snapshot).clone()
}

#[cfg(test)]
mod tests {
    use super::{extension_of, output_path_for, preserve_math_notation, sanitize_stem, supported};
    use std::collections::HashSet;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn extension_matching_is_case_insensitive() {
        assert_eq!(extension_of(std::path::Path::new("A.PdF")), "pdf");
        assert!(supported("docx"));
        assert!(!supported("zip"));
    }

    #[test]
    fn output_paths_increment_for_existing_and_reserved_names() {
        let unique = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let directory = std::env::temp_dir().join(format!("pdf2md-output-{unique}"));
        fs::create_dir_all(&directory).unwrap();
        fs::write(directory.join("report.md"), "already here").unwrap();
        let mut reserved = HashSet::new();
        let first = output_path_for(std::path::Path::new("report.pdf"), &directory, &mut reserved);
        let second = output_path_for(std::path::Path::new("report.docx"), &directory, &mut reserved);
        assert_eq!(first.file_name().unwrap(), "report_1.md");
        assert_eq!(second.file_name().unwrap(), "report_2.md");
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn stems_are_safe_for_windows_output_paths() {
        assert_eq!(sanitize_stem("report:2026?"), "report2026");
        assert_eq!(sanitize_stem("CON"), "document");
        assert_eq!(sanitize_stem("..."), "document");
    }

    #[test]
    fn unsupported_extensions_stay_out_of_supported_set() {
        for extension in ["zip", "exe", "jpg", ""] {
            assert!(!supported(extension));
        }
    }

    #[test]
    fn pandoc_math_representation_is_restored_to_dollar_notation() {
        let source = "Formula: $`a2 + b2 = c2`$\n``` math\n\\int_0^1 x dx\n```\n";
        assert_eq!(
            preserve_math_notation(source.to_owned()),
            "Formula: $a2 + b2 = c2$\n$$\n\\int_0^1 x dx\n$$\n"
        );
    }
}
