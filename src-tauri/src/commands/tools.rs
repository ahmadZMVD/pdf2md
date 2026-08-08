//! Rust-side mirror of scripts/tool_paths.py.
//!
//! Resolves the Python and Pandoc executables with the same contract as
//! the Python helper: bundled binaries in resources/bin/ take priority,
//! then the first working candidate on PATH. Resolution never panics for
//! a missing tool; callers receive status == "unavailable".

use serde::Serialize;
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize)]
pub struct ToolResolution {
    pub status: String,
    pub path: Option<String>,
    pub source: Option<String>,
}

/// Executable basenames probed for `tool`, in priority order.
pub fn candidate_names(tool: &str) -> Vec<&'static str> {
    match tool {
        "python" => vec!["python", "python3", "py"],
        "pandoc" => vec!["pandoc"],
        other => vec![other],
    }
}

/// File names checked inside resources/bin/ for `tool`.
pub fn bundled_file_names(tool: &str) -> Vec<String> {
    let mut names = Vec::new();
    for base in candidate_names(tool) {
        names.push(base.to_string());
        if cfg!(target_os = "windows") {
            names.push(format!("{}.exe", base));
        }
    }
    names
}

fn resource_dirs() -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        dirs.push(cwd.join("resources").join("bin"));
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            dirs.push(parent.join("resources").join("bin"));
        }
    }
    dirs
}

/// Resolve a bundled executable inside resources/bin/ or None.
pub fn resolve_bundled(tool: &str) -> Option<String> {
    for dir in resource_dirs() {
        for name in bundled_file_names(tool) {
            let candidate = dir.join(&name);
            if candidate.is_file() {
                return Some(candidate.to_string_lossy().into_owned());
            }
        }
    }
    None
}

fn which(name: &str) -> Option<String> {
    let path_var = std::env::var_os("PATH")?;
    let mut candidates: Vec<PathBuf> = Vec::new();
    for dir in std::env::split_paths(&path_var) {
        candidates.push(dir.join(name));
        if cfg!(target_os = "windows") {
            candidates.push(dir.join(format!("{}.exe", name)));
            candidates.push(dir.join(format!("{}.cmd", name)));
            candidates.push(dir.join(format!("{}.bat", name)));
        }
    }
    candidates.into_iter().find(|p| p.is_file()).map(|p| p.to_string_lossy().into_owned())
}

/// Resolve the first PATH executable for `tool`, or None.
pub fn resolve_from_path(tool: &str) -> Option<String> {
    for name in candidate_names(tool) {
        if let Some(found) = which(name) {
            return Some(found);
        }
    }
    None
}

/// Resolve `tool` to a ToolResolution; never panics for a missing tool.
pub fn resolve_tool(tool: &str) -> ToolResolution {
    if let Some(path) = resolve_bundled(tool) {
        return ToolResolution {
            status: "bundled".into(),
            path: Some(path),
            source: Some("resources_bin".into()),
        };
    }
    if let Some(path) = resolve_from_path(tool) {
        return ToolResolution {
            status: "path".into(),
            path: Some(path),
            source: Some("system_path".into()),
        };
    }
    ToolResolution { status: "unavailable".into(), path: None, source: None }
}

#[cfg(test)]
mod tests {
    use super::{bundled_file_names, candidate_names};

    #[test]
    fn candidate_names_prioritize_python() {
        let names = candidate_names("python");
        assert_eq!(names, vec!["python", "python3", "py"]);
    }

    #[test]
    fn windows_bundled_names_include_exe() {
        let names = bundled_file_names("pandoc");
        assert!(names.contains(&"pandoc".to_string()));
        if cfg!(target_os = "windows") {
            assert!(names.contains(&"pandoc.exe".to_string()));
        }
    }
}

#[tauri::command]
pub fn resolve_conversion_tool(tool: String) -> ToolResolution {
    resolve_tool(&tool)
}
