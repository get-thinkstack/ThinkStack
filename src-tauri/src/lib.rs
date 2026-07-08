// ThinkStack desktop shell.
//
// On launch this starts the local FastAPI backend (which serves both the React
// UI and the /api endpoints), shows a loading screen that polls the backend and
// auto-navigates to it once it is ready (so a slow model load never shows
// "localhost refused to connect"), and — crucially — kills the backend it
// spawned when the window is closed, so nothing is left orphaned on port 8000.
//
// The paths below target this machine's existing Python venv + project checkout
// (MVP); for distribution the backend would instead be bundled as a sidecar.

use std::net::TcpStream;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

const BACKEND_ADDR: &str = "127.0.0.1:8000";
const PYTHON: &str = r"E:\odysseus\venv\Scripts\python.exe";
const PROJECT_DIR: &str = r"E:\College folder\cs_mini_project";
const MODEL_PATH: &str = r"E:\odysseus\data\models\Qwen3-4B-Instruct-2507-Q4_K_M.gguf";

fn backend_up() -> bool {
    TcpStream::connect(BACKEND_ADDR).is_ok()
}

/// Spawn the FastAPI backend. Returns the child handle so it can be killed on
/// exit. On Windows we suppress the extra console window (CREATE_NO_WINDOW).
fn start_backend() -> Option<Child> {
    let mut cmd = Command::new(PYTHON);
    cmd.args([
        "-m", "uvicorn", "main:app",
        "--host", "127.0.0.1", "--port", "8000",
    ])
    .current_dir(PROJECT_DIR)
    .env("THINKSTACK_LLM_MODEL_PATH", MODEL_PATH)
    .env("THINKSTACK_LLM_CTX_SIZE", "8192");

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
    let pid = child.id();
    #[cfg(windows)]
    {
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
