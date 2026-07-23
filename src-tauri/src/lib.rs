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

/// Detect available VRAM and compute safe gpu_layers.
/// Returns -1 (full offload) if sufficient VRAM, 0 for CPU-only.
fn detect_gpu_layers() -> String {
    // check for NVIDIA GPU via nvidia-smi
    if let Ok(output) = Command::new("nvidia-smi")
        .args(["--query-gpu=memory.total", "--format=csv,noheader,nounits"])
        .output()
    {
        if output.status.success() {
            if let Ok(mem_str) = String::from_utf8(output.stdout) {
                if let Ok(vram_mb) = mem_str.trim().parse::<u64>() {
                    let vram_gb = vram_mb as f64 / 1024.0;
                    // full offload if >= 2GB VRAM, else CPU-only
                    if vram_gb >= 2.0 {
                        return "-1".to_string();
                    }
                }
            }
        }
    }
    "0".to_string()
}

/// Resolve the models directory: bundled data/models or project data/models.
fn models_dir() -> String {
    let project = project_dir();
    let bundled = format!("{project}/data/models");
    if std::path::Path::new(&bundled).is_dir() {
        return bundled;
    }
    // fallback to relative path (the backend config default)
    "data/models".to_string()
}

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

/// Try to locate the backend binary.
///
/// The backend is a PyInstaller *onedir* bundle shipped as a Tauri resource
/// (not an `externalBin` sidecar): a onefile build would re-extract its whole
/// multi-gigabyte payload into %TEMP% on every launch. Tauri unpacks resources
/// into the resource dir, which on Windows/Linux is the directory holding the
/// main executable, so the bundle lands in `api/` beside it.
fn sidecar_path() -> Option<std::path::PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?;

    let candidates = [
        // packaged: resource folder next to the main binary
        dir.join("api").join("thinkstack-api.exe"),
        dir.join("api").join("thinkstack-api"),
        // macOS bundles put resources in Contents/Resources
        dir.join("../Resources/api/thinkstack-api"),
        // locally built bundle, before packaging
        std::path::PathBuf::from(project_dir())
            .join("dist/thinkstack-api/thinkstack-api.exe"),
        std::path::PathBuf::from(project_dir())
            .join("dist/thinkstack-api/thinkstack-api"),
    ];

    candidates.iter().find(|c| c.is_file()).cloned()
}

/// Forward inference settings from the real environment to the backend.
///
/// Deliberately sets no defaults of its own. GPU offload is machine-specific:
/// `THINKSTACK_LLM_GPU_LAYERS=-1` requires a CUDA build of llama-cpp-python, and
/// the loader raises rather than silently falling back to CPU - so forcing -1
/// here would turn "no CUDA on this machine" into a hard crash at model load.
///
/// The machine's own value belongs in the gitignored `.env` shipped next to the
/// sidecar, which `config.py` resolves relative to the executable rather than
/// the working directory. Absent that, the Python default (0, CPU-only) applies
/// and the app runs anywhere.
fn apply_inference_env(cmd: &mut Command) {
    for key in [
        "THINKSTACK_LLM_GPU_LAYERS",
        "THINKSTACK_LLM_MODEL_PATH",
        "THINKSTACK_LLM_CTX_SIZE",
    ] {
        if let Ok(value) = std::env::var(key) {
            cmd.env(key, value);
        }
    }
}

fn backend_up() -> bool {
    TcpStream::connect(BACKEND_ADDR).is_ok()
}

/// Spawn the FastAPI backend.
///
/// Prefers the bundled sidecar binary (production). Falls back to
/// `python -m uvicorn` for development when no sidecar is found.
fn start_backend() -> Option<Child> {
    let gpu_layers = detect_gpu_layers();
    let model_dir = models_dir();

    // ── try sidecar first (production builds) ──
    if let Some(sidecar) = sidecar_path() {
        let mut cmd = Command::new(&sidecar);
        cmd.args(["--host", "127.0.0.1", "--port", "8000"]);

        // run from the bundle's own folder so its .env (model path) resolves
        if let Some(dir) = sidecar.parent() {
            cmd.current_dir(dir);
        }

        // pass hardware-detected settings to the backend
        cmd.env("THINKSTACK_LLM_GPU_LAYERS", &gpu_layers);
        cmd.env("THINKSTACK_LLM_MODEL_PATH", &model_dir);

        if let Ok(model) = std::env::var("THINKSTACK_LLM_MODEL_PATH") {
            cmd.env("THINKSTACK_LLM_MODEL_PATH", model);
        }
        apply_inference_env(&mut cmd);

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

    apply_inference_env(&mut cmd);
    // pass hardware-detected settings to the backend
    cmd.env("THINKSTACK_LLM_GPU_LAYERS", &gpu_layers);
    cmd.env("THINKSTACK_LLM_MODEL_PATH", &model_dir);

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
        // /T kills the whole tree, /F forces it - belt and suspenders.
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

    let mut builder = tauri::Builder::default().plugin(tauri_plugin_opener::init());

    // auto-updater (desktop only): lets the frontend check the signed manifest
    // on github releases and install a new version in-app. `process` is used to
    // relaunch after an update installs.
    #[cfg(not(any(target_os = "android", target_os = "ios")))]
    {
        builder = builder
            .plugin(tauri_plugin_updater::Builder::new().build())
            .plugin(tauri_plugin_process::init());
    }

    let app = builder
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
