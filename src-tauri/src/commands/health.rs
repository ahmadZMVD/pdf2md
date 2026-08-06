use serde::Serialize;
use std::process::{Command, Output, Stdio};
use std::thread::sleep;
use std::time::{Duration, Instant};

const PROBE_TIMEOUT: Duration = Duration::from_secs(8);

#[derive(Debug, Serialize)]
pub struct LocalEnvironment {
    pub python_available: bool,
    pub python_version: String,
    pub pymupdf4llm_available: bool,
    pub pymupdf4llm_version: String,
    pub pandoc_available: bool,
    pub pandoc_version: String,
    pub git_cli_available: bool,
    pub git_version: String,
    pub github_cli_available: bool,
    pub github_cli_version: String,
}

#[derive(Debug, Serialize)]
pub struct SystemHealth {
    pub status: String,
    pub local_environment: LocalEnvironment,
    pub build_architecture: String,
    pub os: String,
}

struct ProbeResult {
    success: bool,
    output: String,
}

fn run_probe(program: &str, args: &[&str]) -> ProbeResult {
    let mut child = match Command::new(program)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(child) => child,
        Err(_) => {
            return ProbeResult {
                success: false,
                output: String::new(),
            }
        }
    };

    let deadline = Instant::now() + PROBE_TIMEOUT;
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                let output = child
                    .wait_with_output()
                    .map(format_output)
                    .unwrap_or_default();
                return ProbeResult {
                    success: status.success(),
                    output,
                };
            }
            Ok(None) if Instant::now() >= deadline => {
                let _ = child.kill();
                let _ = child.wait();
                return ProbeResult {
                    success: false,
                    output: String::new(),
                };
            }
            Ok(None) => sleep(Duration::from_millis(20)),
            Err(_) => {
                let _ = child.kill();
                let _ = child.wait();
                return ProbeResult {
                    success: false,
                    output: String::new(),
                };
            }
        }
    }
}

fn format_output(output: Output) -> String {
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    let combined = if stdout.trim().is_empty() {
        stderr
    } else {
        stdout
    };
    combined.trim().to_owned()
}

fn first_line(value: &str) -> String {
    value.lines().next().unwrap_or_default().trim().to_owned()
}

fn probe_python() -> (bool, String, bool, String) {
    const IMPORT_CHECK: &str =
        "import pymupdf4llm; print(getattr(pymupdf4llm, '__version__', 'installed'))";
    let candidates = [
        (
            "python",
            &["--version"][..],
            &["-c", IMPORT_CHECK][..],
        ),
        (
            "py",
            &["-3", "--version"][..],
            &["-3", "-c", IMPORT_CHECK][..],
        ),
    ];

    for (program, version_args, import_args) in candidates {
        let version = run_probe(program, version_args);
        if version.success {
            let package = run_probe(program, import_args);
            return (
                true,
                first_line(&version.output),
                package.success,
                first_line(&package.output),
            );
        }
    }

    (false, String::new(), false, String::new())
}

fn probe_single(program: &str, args: &[&str]) -> (bool, String) {
    let result = run_probe(program, args);
    (result.success, first_line(&result.output))
}

#[tauri::command]
pub fn check_system_health() -> SystemHealth {
    let (python_available, python_version, pymupdf4llm_available, pymupdf4llm_version) =
        probe_python();
    let (pandoc_available, pandoc_output) = probe_single("pandoc", &["-v"]);
    let (git_cli_available, git_output) = probe_single("git", &["--version"]);
    let (github_cli_available, github_cli_output) = probe_single("gh", &["--version"]);

    let all_dependencies_available = python_available
        && pymupdf4llm_available
        && pandoc_available
        && git_cli_available
        && github_cli_available;

    SystemHealth {
        status: if all_dependencies_available {
            "ok"
        } else {
            "degraded"
        }
        .to_owned(),
        local_environment: LocalEnvironment {
            python_available,
            python_version,
            pymupdf4llm_available,
            pymupdf4llm_version,
            pandoc_available,
            pandoc_version: pandoc_output,
            git_cli_available,
            git_version: git_output,
            github_cli_available,
            github_cli_version: github_cli_output,
        },
        build_architecture: "cloud_hybrid_tauri_v2".to_owned(),
        os: if cfg!(target_os = "windows") {
            "windows"
        } else if cfg!(target_os = "macos") {
            "macos"
        } else {
            "linux"
        }
        .to_owned(),
    }
}

#[cfg(test)]
mod tests {
    use super::{first_line, run_probe};

    #[test]
    fn first_line_discards_empty_prefix_and_following_lines() {
        assert_eq!(first_line("\n  first result  \nsecond result"), "first result");
    }

    #[test]
    fn subprocess_probe_executes_a_real_bounded_process() {
        let result = if cfg!(target_os = "windows") {
            run_probe("cmd.exe", &["/C", "echo phase1-health-probe"])
        } else {
            run_probe("sh", &["-c", "printf phase1-health-probe"])
        };

        assert!(result.success);
        assert_eq!(first_line(&result.output), "phase1-health-probe");
    }
}
