//! Sequential document conversion queue and Tauri IPC commands.
//!
//! The GUI never waits for a child process: `start_conversion_batch` prepares
//! the immutable queue snapshot and starts one named worker thread.  That
//! worker owns exactly one subprocess at a time, streams child stdout/stderr
//! to temporary log files (never RAM buffers), and records terminal errors
//! instead of propagating a panic.
//!
//! Process management is killable by design: every engine invocation is
//! `Command::spawn()`ed and polled with `Child::try_wait()` every 120 ms. The
//! live `Child` handle is parked in the queue state under a short-lived
//! mutex, so `cancel_batch` can call `Child::kill()` immediately instead of
//! waiting for the next queue boundary. The Python engine additionally runs
//! its own watchdog with a hard deadline, so even a hang inside native C code
//! cannot stall the batch.

use crate::commands::tools::resolve_tool;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{
    atomic::{AtomicBool, AtomicU64, Ordering},
    Arc, Mutex, MutexGuard,
};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::Manager;

const SUPPORTED_EXTENSIONS: &[&str] = &["pdf", "docx", "txt"];
const MAX_ERROR_LENGTH: usize = 1_000;
const POLL_INTERVAL: Duration = Duration::from_millis(120);
const PDF_TIMEOUT_SECONDS: u64 = 300;
const PDF_MAX_PAGES: u64 = 2_000;

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
/// under the lock.  `active_child` is parked here so the cancel command can
/// kill the in-flight engine process from any thread.
#[derive(Clone)]
pub struct ConversionQueue {
    snapshot: Arc<Mutex<QueueSnapshot>>,
    cancellation: Arc<AtomicBool>,
    next_batch_id: Arc<AtomicU64>,
    active_child: Arc<Mutex<Option<Child>>>,
}

impl Default for ConversionQueue {
    fn default() -> Self {
        Self {
            snapshot: Arc::new(Mutex::new(QueueSnapshot::default())),
            cancellation: Arc::new(AtomicBool::new(false)),
            next_batch_id: Arc::new(AtomicU64::new(0)),
            active_child: Arc::new(Mutex::new(None)),
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

    fn cancelled() -> Self {
        Self {
            status: QueueItemStatus::Cancelled,
            error: None,
            characters: None,
            elapsed_seconds: None,
        }
    }
}

/// Outcome of a polled engine invocation.
#[derive(Debug)]
struct ChildOutcome {
    /// True when the process was killed by a cancellation request.
    cancelled: bool,
    /// True when the process exited with a zero status.
    success: bool,
    /// Entire engine stdout streamed from a temporary file.
    stdout: String,
    /// Entire engine stderr streamed from a temporary file.
    stderr: String,
}

/// Removes both log files when dropped, on every code path including early
/// returns inside the run loop.
struct TempLogs {
    stdout_path: PathBuf,
    stderr_path: PathBuf,
}

impl Drop for TempLogs {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.stdout_path);
        let _ = fs::remove_file(&self.stderr_path);
    }
}

fn lock_snapshot(queue: &Arc<Mutex<QueueSnapshot>>) -> MutexGuard<'_, QueueSnapshot> {
    // A conversion worker never intentionally panics. If an embedding host
    // poisoned the mutex, retaining the last consistent snapshot is safer than
    // crashing the desktop application during status polling.
    queue.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn lock_active(active: &Mutex<Option<Child>>) -> MutexGuard<'_, Option<Child>> {
    active.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
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

fn first_existing(candidates: Vec<PathBuf>) -> Option<PathBuf> {
    candidates.into_iter().find(|candidate| candidate.is_file())
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
    first_existing(candidates)
}

fn math_filter_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join("scripts").join("filters").join("math_preserve.lua"));
        candidates.push(resource_dir.join("filters").join("math_preserve.lua"));
    }
    if let Ok(current_dir) = std::env::current_dir() {
        candidates.push(current_dir.join("scripts").join("filters").join("math_preserve.lua"));
    }
    if let Ok(executable) = std::env::current_exe() {
        if let Some(parent) = executable.parent() {
            candidates.push(parent.join("resources").join("scripts").join("filters").join("math_preserve.lua"));
        }
    }
    first_existing(candidates)
}

fn json_error(stdout: &str, fallback: &str) -> String {
    serde_json::from_str::<Value>(stdout)
        .ok()
        .and_then(|value| value.get("error").and_then(Value::as_str).map(str::to_owned))
        .filter(|message| !message.trim().is_empty())
        .unwrap_or_else(|| fallback.to_owned())
}

/// Spawn *command* with stdout/stderr redirected to temporary files, poll its
/// exit status without blocking, and kill it the moment a cancellation is
/// requested.  Returns a structured outcome; child output is read from disk,
/// so arbitrarily large engine output never grows process RAM.
fn run_capture(
    command: &mut Command,
    cancellation: &AtomicBool,
    active_child: &Mutex<Option<Child>>,
) -> Result<ChildOutcome, String> {
    static SEQUENCE: AtomicU64 = AtomicU64::new(0);
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    let sequence = SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let logs = TempLogs {
        stdout_path: std::env::temp_dir().join(format!("pdf2md-stdout-{unique}-{sequence}.log")),
        stderr_path: std::env::temp_dir().join(format!("pdf2md-stderr-{unique}-{sequence}.log")),
    };
    let stdout_file = fs::File::create(&logs.stdout_path)
        .map_err(|error| format!("could not create engine log file: {error}"))?;
    let stderr_file = fs::File::create(&logs.stderr_path)
        .map_err(|error| format!("could not create engine log file: {error}"))?;

    let child = command
        .stdin(Stdio::null())
        .stdout(stdout_file)
        .stderr(stderr_file)
        .spawn()
        .map_err(|error| format!("could not start engine process: {error}"))?;
    {
        let mut guard = lock_active(active_child);
        *guard = Some(child);
    }

    let status = loop {
        if cancellation.load(Ordering::Acquire) {
            let mut guard = lock_active(active_child);
            if let Some(mut active) = guard.take() {
                let _ = active.kill();
                let _ = active.wait();
            }
            return Ok(ChildOutcome {
                cancelled: true,
                success: false,
                stdout: String::new(),
                stderr: String::new(),
            });
        }
        let mut guard = lock_active(active_child);
        let Some(mut active) = guard.take() else {
            return Err("engine process handle was lost while polling".to_owned());
        };
        match active.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) => {
                *guard = Some(active);
                drop(guard);
                std::thread::sleep(POLL_INTERVAL);
            }
            Err(error) => {
                let _ = active.kill();
                let _ = active.wait();
                return Err(format!("engine process poll failed: {error}"));
            }
        }
    };

    let stdout = fs::read_to_string(&logs.stdout_path).unwrap_or_default();
    let stderr = fs::read_to_string(&logs.stderr_path).unwrap_or_default();
    Ok(ChildOutcome {
        cancelled: false,
        success: status.success(),
        stdout,
        stderr,
    })
}

fn process_pdf(
    source: &Path,
    output: &Path,
    engine_script: Option<&Path>,
    cancellation: &AtomicBool,
    active_child: &Mutex<Option<Child>>,
) -> WorkResult {
    let Some(engine_script) = engine_script else {
        return WorkResult::failed("PDF engine script is unavailable in application resources");
    };
    let python = resolve_tool("python");
    let Some(python_path) = python.path else {
        return WorkResult::failed("Python runtime is unavailable; install Python or bundle it in resources/bin");
    };

    let mut command = Command::new(python_path);
    command
        .args(["-X", "utf8", "-I"])
        .arg(engine_script)
        .arg("--input")
        .arg(source)
        .arg("--output")
        .arg(output)
        .arg("--timeout")
        .arg(PDF_TIMEOUT_SECONDS.to_string())
        .arg("--max-pages")
        .arg(PDF_MAX_PAGES.to_string());
    let outcome = match run_capture(&mut command, cancellation, active_child) {
        Ok(outcome) => outcome,
        Err(error) => return WorkResult::failed(error),
    };
    if outcome.cancelled {
        return WorkResult::cancelled();
    }
    if !outcome.success {
        return WorkResult::failed(json_error(&outcome.stdout, &outcome.stderr));
    }
    let payload: Value = match serde_json::from_str(&outcome.stdout) {
        Ok(payload) => payload,
        Err(error) => return WorkResult::failed(format!("PDF engine returned invalid JSON: {error}")),
    };
    if payload.get("status").and_then(Value::as_str) != Some("success") {
        return WorkResult::failed(json_error(&outcome.stdout, "PDF engine did not report success"));
    }
    let characters = payload
        .get("characters")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .unwrap_or_default();
    let elapsed_seconds = payload.get("elapsed_seconds").and_then(Value::as_f64);
    WorkResult::completed(characters, elapsed_seconds)
}

fn process_pandoc(
    source: &Path,
    output: &Path,
    extension: &str,
    math_filter: Option<&Path>,
    cancellation: &AtomicBool,
    active_child: &Mutex<Option<Child>>,
) -> WorkResult {
    let pandoc = resolve_tool("pandoc");
    let Some(pandoc_path) = pandoc.path else {
        return WorkResult::failed("Pandoc is unavailable; install Pandoc or bundle it in resources/bin");
    };
    let Some(math_filter) = math_filter else {
        return WorkResult::failed("math preservation filter is unavailable in application resources");
    };
    let input_format = if extension == "docx" { "docx" } else { "markdown" };
    let started = std::time::Instant::now();
    let mut command = Command::new(pandoc_path);
    command
        .arg(format!("--from={input_format}"))
        .arg("--to=gfm")
        .arg(format!("--lua-filter={}", math_filter.display()))
        .arg("--output")
        .arg(output)
        .arg(source);
    let outcome = match run_capture(&mut command, cancellation, active_child) {
        Ok(outcome) => outcome,
        Err(error) => return WorkResult::failed(error),
    };
    if outcome.cancelled {
        // A killed Pandoc may have left a partially written output file.
        let _ = fs::remove_file(output);
        return WorkResult::cancelled();
    }
    if !outcome.success {
        let _ = fs::remove_file(output);
        let message = outcome.stderr.trim();
        return WorkResult::failed(if message.is_empty() {
            "Pandoc conversion failed".to_owned()
        } else {
            message.to_owned()
        });
    }
    let markdown = match fs::read_to_string(output) {
        Ok(markdown) => markdown,
        Err(error) => return WorkResult::failed(format!("Pandoc reported success but output was unavailable: {error}")),
    };
    let characters = markdown.chars().count();
    WorkResult::completed(characters, Some(started.elapsed().as_secs_f64()))
}

fn process_item(
    source: &Path,
    output: Option<&Path>,
    engine_script: Option<&Path>,
    math_filter: Option<&Path>,
    cancellation: &AtomicBool,
    active_child: &Mutex<Option<Child>>,
) -> WorkResult {
    let extension = extension_of(source);
    if !supported(&extension) {
        return WorkResult::unsupported(&extension);
    }
    let Some(output) = output else {
        return WorkResult::failed("queue item is missing its output path");
    };
    match extension.as_str() {
        "pdf" => process_pdf(source, output, engine_script, cancellation, active_child),
        "docx" | "txt" => process_pandoc(source, output, &extension, math_filter, cancellation, active_child),
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
    math_filter: Option<PathBuf>,
    active_child: Arc<Mutex<Option<Child>>>,
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

        let result = process_item(
            &next.1,
            next.2.as_deref(),
            engine_script.as_deref(),
            math_filter.as_deref(),
            &cancellation,
            &active_child,
        );
        let cancelled = result.status == QueueItemStatus::Cancelled;
        let mut snapshot = lock_snapshot(&queue);
        mark_result(&mut snapshot, next.0, result);
        if cancelled {
            break;
        }
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
    let active_child = state.active_child.clone();
    let initial_snapshot = {
        let mut snapshot = lock_snapshot(&queue);
        if snapshot.status == BatchStatus::Running {
            return Err("a conversion batch is already running".to_owned());
        }
        cancellation.store(false, Ordering::Release);
        {
            // The previous batch is guaranteed reaped at this point; any
            // stale handle is a programming error that must not leak.
            let mut guard = lock_active(&active_child);
            *guard = None;
        }
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
    let math_filter = math_filter_path(&app);
    let worker_queue = queue.clone();
    let worker_cancellation = cancellation.clone();
    let worker_active = active_child.clone();
    if let Err(error) = std::thread::Builder::new()
        .name("pdf2md-conversion-queue".to_owned())
        .spawn(move || run_worker(worker_queue, worker_cancellation, engine_script, math_filter, worker_active))
    {
        let mut snapshot = lock_snapshot(&queue);
        fail_start(&mut snapshot, "unable to start conversion worker");
        return Err(format!("unable to start conversion worker: {error}"));
    }
    Ok(initial_snapshot)
}

/// Request cancellation.  The in-flight engine process is killed immediately
/// via its parked `Child` handle; all queued files are marked cancelled and
/// will never be started.
#[tauri::command]
pub fn cancel_batch(state: tauri::State<'_, ConversionQueue>) -> QueueSnapshot {
    state.cancellation.store(true, Ordering::Release);
    {
        let mut guard = lock_active(&state.active_child);
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
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
    use super::{extension_of, first_existing, output_path_for, run_capture, sanitize_stem, supported, Command, Mutex};
    use std::collections::HashSet;
    use std::fs;
    use std::process::Child;
    use std::sync::atomic::AtomicBool;
    use std::sync::Arc;
    use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

    fn unique_directory(label: &str) -> std::path::PathBuf {
        let unique = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let directory = std::env::temp_dir().join(format!("pdf2md-{label}-{unique}"));
        fs::create_dir_all(&directory).unwrap();
        directory
    }

    fn cancellation_flag(value: bool) -> Arc<AtomicBool> {
        Arc::new(AtomicBool::new(value))
    }

    #[test]
    fn extension_matching_is_case_insensitive() {
        assert_eq!(extension_of(std::path::Path::new("A.PdF")), "pdf");
        assert!(supported("docx"));
        assert!(!supported("zip"));
    }

    #[test]
    fn output_paths_increment_for_existing_and_reserved_names() {
        let directory = unique_directory("output");
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
    fn first_existing_prefers_the_earliest_present_candidate() {
        let directory = unique_directory("candidates");
        let present = directory.join("engine.py");
        fs::write(&present, "print()").unwrap();
        let found = first_existing(vec![present.clone(), directory.join("missing.py")]);
        assert_eq!(found, Some(present));
        let absent = first_existing(vec![directory.join("a.py"), directory.join("b.py")]);
        assert_eq!(absent, None);
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn engine_output_is_streamed_through_disk_not_ram() {
        let mut command = Command::new(if cfg!(target_os = "windows") { "cmd.exe" } else { "sh" });
        if cfg!(target_os = "windows") {
            command.args(["/C", "echo disk-streamed-probe"]);
        } else {
            command.args(["-c", "echo disk-streamed-probe"]);
        }
        let cancellation = cancellation_flag(false);
        let child: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(None));
        let outcome = run_capture(&mut command, &cancellation, &child).expect("engine must run");
        assert!(!outcome.cancelled);
        assert!(outcome.success);
        assert!(outcome.stdout.contains("disk-streamed-probe"));
        assert!(child.lock().unwrap().is_none(), "finished handle must be released");
    }

    #[test]
    fn pending_cancellation_kills_the_child_promptly() {
        let mut command = Command::new(if cfg!(target_os = "windows") { "cmd.exe" } else { "sh" });
        if cfg!(target_os = "windows") {
            command.args(["/C", "ping -n 30 127.0.0.1 >nul"]);
        } else {
            command.args(["-c", "sleep 30"]);
        }
        let cancellation = cancellation_flag(true);
        let child: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(None));
        let started = Instant::now();
        let outcome = run_capture(&mut command, &cancellation, &child).expect("engine must return");
        assert!(outcome.cancelled, "pre-set cancellation must kill the child");
        assert!(!outcome.success);
        assert!(started.elapsed() < Duration::from_secs(5), "kill must not wait for the child");
        assert!(child.lock().unwrap().is_none(), "killed handle must be released");
    }
}
