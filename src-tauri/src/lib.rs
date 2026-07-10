// ThinkStack desktop shell.
//
// On launch this starts the local FastAPI backend, shows a loading screen that
// polls the backend and auto-navigates to it once it is ready (so a slow model
// load never shows "localhost refused to connect"), and kills the backend it
// spawned when the window is closed, so nothing is left orphaned on port 8000.
//
// In production builds the backend is a PyInstaller-frozen sidecar binary
// (`thinkstack-api`) bundled by Tauri. In development (`cargo tauri dev`) it
// falls back to running `python -m uvicorn` from the project venv.

use std::net::TcpStream;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

const BACKEND_ADDR: &str = "127.0.0.1:8000";

/// Resolve the python interpreter: env var → project venv → system python3.
fn python_path() -> String {
    if let Ok(p) = std::env::var("THINKSTACK_PYTHON") {
        return p;
    }
    // look for the venv in the project directory
    let project = project_dir();
    let venv_unix = format!("{project}/.venv/bin/python3");
    let venv_win = format!("{project}\\.venv\\Scripts\\python.exe");
    if std::path::Path::new(&venv_unix).exists() {
        return venv_unix;
    }
    if std::path::Path::new(&venv_win).exists() {
        return venv_win;
    }
    "python3".to_string()
}

/// Resolve the project directory: env var → parent of the tauri binary → cwd.
fn project_dir() -> String {
    if let Ok(p) = std::env::var("THINKSTACK_PROJECT_DIR") {
        return p;
    }
    // during `cargo tauri dev`, the binary runs from the project root already
    if let Ok(cwd) = std::env::current_dir() {
        if cwd.join("main.py").exists() {
            return cwd.to_string_lossy().to_string();
        }
        // src-tauri is one level down from the project root
        if let Some(parent) = cwd.parent() {
            if parent.join("main.py").exists() {
                return parent.to_string_lossy().to_string();
            }
        }
    }
    ".".to_string()
}

/// Try to locate the sidecar binary next to the running executable.
/// In production Tauri bundles place sidecars adjacent to the main binary.
fn sidecar_path() -> Option<std::path::PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?;

    // Tauri names the sidecar with the target triple, but the resolved path
    // from the bundle is just the bare name next to the exe.
    let candidates = [
        dir.join("thinkstack-api"),
        dir.join("thinkstack-api.exe"),
    ];

    for candidate in &candidates {
        if candidate.is_file() {
            return Some(candidate.clone());
        }
    }
    None
}

fn backend_up() -> bool {
    TcpStream::connect(BACKEND_ADDR).is_ok()
}

/// Spawn the FastAPI backend.
///
/// Prefers the bundled sidecar binary (production). Falls back to
/// `python -m uvicorn` for development when no sidecar is found.
fn start_backend() -> Option<Child> {
    // ── try sidecar first (production builds) ──
    if let Some(sidecar) = sidecar_path() {
        let mut cmd = Command::new(&sidecar);
        cmd.args(["--host", "127.0.0.1", "--port", "8000"]);

        if let Ok(model) = std::env::var("THINKSTACK_LLM_MODEL_PATH") {
            cmd.env("THINKSTACK_LLM_MODEL_PATH", model);
        }

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        if let Ok(child) = cmd.spawn() {
            return Some(child);
        }
    }

    // ── fallback: python venv (development) ──
    let python = python_path();
    let project = project_dir();

    let mut cmd = Command::new(&python);
    cmd.args([
        "-m", "uvicorn", "main:app",
        "--host", "127.0.0.1", "--port", "8000",
    ])
    .current_dir(&project);

    if let Ok(model) = std::env::var("THINKSTACK_LLM_MODEL_PATH") {
        cmd.env("THINKSTACK_LLM_MODEL_PATH", model);
    }

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    cmd.spawn().ok()
}

/// Force-kill the backend process tree so no uvicorn/python lingers on 8000.
fn kill_backend(child: &mut Child) {
    #[cfg(windows)]
    {
        let pid = child.id();
        // /T kills the whole tree, /F forces it — belt and suspenders.
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .output();
    }
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Only manage (and later kill) a backend WE started. If one is already up we
    // attach to it and leave it running on exit.
    let managed: Mutex<Option<Child>> = Mutex::new(None);
    if !backend_up() {
        if let Some(child) = start_backend() {
            *managed.lock().unwrap() = Some(child);
        }
        // give the socket a brief moment to come up; the loading page handles
        // the rest by polling, so we don't block the window on a slow model load
        std::thread::sleep(Duration::from_millis(400));
    }

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(move |_app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            if let Some(mut child) = managed.lock().unwrap().take() {
                kill_backend(&mut child);
            }
        }
    });
}
