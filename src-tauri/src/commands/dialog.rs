//! Native folder picker command.
//!
//! The frontend settings modal's "Browse…" control never hardcodes a path:
//! it delegates to this command, which opens the operating system folder
//! dialog via the dialog plugin. A cancelled dialog returns `null` so the
//! frontend can keep its previous value; a chosen folder is normalized to
//! forward slashes so the path contract matches every other frontend field.

use tauri_plugin_dialog::{DialogExt, FilePath};

/// Normalize a picked path to the app-wide contract (forward slashes,
/// no trailing slash). Pure function so it stays unit-testable on any host.
pub fn normalize_picked_path(path: &str) -> String {
    let trimmed = path.trim();
    let forward = trimmed.replace('\\', "/");
    let mut cleaned: String = forward.trim_end_matches('/').to_owned();
    if cleaned.is_empty() {
        cleaned = "/".to_owned();
    }
    cleaned
}

#[tauri::command]
pub fn pick_output_folder(app: tauri::AppHandle) -> Option<String> {
    let selected = app
        .dialog()
        .file()
        .blocking_pick_folder()
        .and_then(|folder| match folder {
            FilePath::Path(path) => Some(path.to_string_lossy().into_owned()),
            FilePath::Url(_) => None,
        })?;
    Some(normalize_picked_path(&selected))
}

#[cfg(test)]
mod tests {
    use super::normalize_picked_path;

    #[test]
    fn windows_paths_are_normalized_to_forward_slashes() {
        assert_eq!(normalize_picked_path("C:\\Users\\Ahmad\\Docs"), "C:/Users/Ahmad/Docs");
        assert_eq!(normalize_picked_path("D:/out\\nested\\"), "D:/out/nested");
    }

    #[test]
    fn trailing_slashes_and_whitespace_are_trimmed() {
        assert_eq!(normalize_picked_path("  C:/converted/  "), "C:/converted");
        assert_eq!(normalize_picked_path("C:\\"), "C:");
    }

    #[test]
    fn empty_selection_cannot_collapse_to_an_invalid_path() {
        assert_eq!(normalize_picked_path("   "), "/");
        assert_eq!(normalize_picked_path(""), "/");
    }
}
