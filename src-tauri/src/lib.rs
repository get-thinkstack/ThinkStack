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

use std::io::{BufRead, BufReader, Write};
use std::net::TcpStream;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::{AppHandle, Emitter, Manager};

mod diagnosis;

// tauri.conf.json's frontendDist points at frontend/public -- the LOADING
// SCREEN only, not the application. The window opens loading.html, then
// navigates here once the backend answers, and the backend serves the real UI
// from the copy PyInstaller bundled.
//
// It used to point at frontend/dist, which embedded the whole SPA a second
// time: 872 KB of dead weight in every installer, and two copies of the
// interface that could disagree about what they were. tauri.conf.json cannot
// hold a comment (it rejects unknown fields), so the reason lives here, next
// to the address that makes the embedded copy unnecessary.
const BACKEND_ADDR: &str = "127.0.0.1:8000";

/// How long to wait for the backend socket before declaring the launch failed.
///
/// A beta tester sat on a spinner for 200s because the old loading screen
/// retried forever with no upper bound and no error path. Waiting forever is not
/// patience, it is an absent failure mode: the user cannot tell a slow first
/// launch from a backend that died on line one. 180s is generous for a cold
/// start off compressed AppImage storage and still terminates.
const STARTUP_TIMEOUT: Duration = Duration::from_secs(180);

/// Structured startup progress, mirrored to the loading screen.
#[derive(Clone, serde::Serialize)]
struct Step {
    phase: String,
    detail: String,
    elapsed_ms: u128,
}

/// Terminal failure, carrying enough to act on without a terminal.
#[derive(Clone, serde::Serialize)]
struct Failure {
    error: String,
    log_path: String,
    tail: Vec<String>,
}

/// Every step emitted so far, so the loading screen can catch up on what it
/// missed. The webview needs ~100-300ms to attach its listeners, and diagnosis
/// finishes well inside that -- without a replay the first (and most useful)
/// lines are emitted into the void and the panel opens blank.
#[derive(Default)]
struct StartupLog(Mutex<Vec<Step>>);

/// Steps recorded before the window was listening. Called by the loading screen
/// on load; the live event stream carries everything after that.
#[tauri::command]
fn startup_log(state: tauri::State<'_, StartupLog>) -> Vec<Step> {
    state.0.lock().map(|s| s.clone()).unwrap_or_default()
}

fn emit_step(app: &AppHandle, started: Instant, phase: &str, detail: impl Into<String>) {
    let step = Step {
        phase: phase.to_string(),
        detail: detail.into(),
        elapsed_ms: started.elapsed().as_millis(),
    };
    if let Some(state) = app.try_state::<StartupLog>() {
        if let Ok(mut log) = state.0.lock() {
            log.push(step.clone());
            // bounded: a chatty backend must not grow this without limit
            if log.len() > 400 {
                log.remove(0);
            }
        }
    }

    // Mirror to disk. The on-screen panel disappears with the window, and a
    // startup bug is exactly the case where the user cannot copy anything out
    // of it -- so the same trace has to survive on disk, timestamped, for a bug
    // report. Backend output lands in this file too, interleaved in real order.
    if step.phase != "backend" {
        if let Ok(mut f) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(log_path(app))
        {
            let _ = writeln!(
                f,
                "[{:>7}ms] {}: {}",
                step.elapsed_ms, step.phase, step.detail
            );
        }
    }

    // A failed emit means the window is already gone; nothing to recover.
    let _ = app.emit("startup:step", step);
}

/// Where backend output is written so a failed launch can be diagnosed after
/// the fact. Falls back to the temp dir if the platform log dir is unavailable:
/// losing the log is worse than writing it somewhere unexpected.
fn log_path(app: &AppHandle) -> std::path::PathBuf {
    let dir = app
        .path()
        .app_log_dir()
        .unwrap_or_else(|_| std::env::temp_dir().join("ThinkStack"));
    let _ = std::fs::create_dir_all(&dir);
    dir.join("backend.log")
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
fn sidecar_path(app: &AppHandle) -> Option<std::path::PathBuf> {
    let mut candidates: Vec<std::path::PathBuf> = Vec::new();

    // Ask Tauri where it put the resources. This is the only source that is
    // correct on every packaging format; the hand-rolled guesses below are
    // fallbacks for running out of a build tree.
    if let Ok(res) = app.path().resource_dir() {
        candidates.push(res.join("api").join("thinkstack-api.exe"));
        candidates.push(res.join("api").join("thinkstack-api"));
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            // packaged: resource folder next to the main binary
            candidates.push(dir.join("api").join("thinkstack-api.exe"));
            candidates.push(dir.join("api").join("thinkstack-api"));
            // macOS bundles put resources in Contents/Resources
            candidates.push(dir.join("../Resources/api/thinkstack-api"));
            // Linux .deb and AppImage: the binary lands in usr/bin while Tauri
            // puts resources in usr/lib/<ProductName>/. Without this the lookup
            // failed inside the AppImage and we silently fell back to running
            // `python3 -m uvicorn` -- which the AppImage's own AppRun then broke
            // by exporting PYTHONHOME=$APPDIR/usr, producing
            // "Fatal Python error: Failed to import encodings module".
            candidates.push(dir.join("../lib/ThinkStack/api/thinkstack-api"));
        }
    }

    // locally built bundle, before packaging
    let project = std::path::PathBuf::from(project_dir());
    candidates.push(project.join("dist/thinkstack-api/thinkstack-api.exe"));
    candidates.push(project.join("dist/thinkstack-api/thinkstack-api"));

    candidates.into_iter().find(|c| c.is_file())
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
/// Remove interpreter-controlling variables inherited from our own launcher.
///
/// The AppImage runtime's AppRun exports `PYTHONHOME=$APPDIR/usr/` (and
/// PYTHONPATH) before running the app, and every child inherits them. A frozen
/// PyInstaller binary mostly shrugs this off, but a system `python3` does not:
/// it looks for its stdlib under the AppDir, finds none, and dies with
/// "Fatal Python error: Failed to import encodings module" before executing a
/// single line of ours. Clearing them costs nothing -- the backend resolves its
/// own paths relative to its executable, never from these.
fn scrub_python_env(cmd: &mut Command) {
    for key in [
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONEXECUTABLE",
        "PYTHONNOUSERSITE",
    ] {
        cmd.env_remove(key);
    }

    // Keep the working directory off sys.path.
    //
    // nltk 3.10.1 added a security hook that REFUSES to import xml.etree when
    // the current directory is importable, and the frozen backend imports nltk
    // during startup. The result was "Blocked import of xml.etree from current
    // working directory", the process died before serving anything, and every
    // platform failed identically -- from a dependency release, with no change
    // on our side.
    //
    // The backend never needs the working directory on its path: PyInstaller
    // resolves its modules from the bundle. Setting this makes that explicit
    // and closes the whole class of "something in the CWD shadowed a stdlib
    // module", which is also how a stray file next to the app could hijack an
    // import.
    cmd.env("PYTHONSAFEPATH", "1");
}

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
fn start_backend(app: &AppHandle, profile: &diagnosis::HwProfile) -> Option<Child> {
    // The hardware profile is measured once by the caller and handed over as
    // JSON in THINKSTACK_HW_PROFILE, so the backend never imports torch just to
    // size the model. gpu_layers is also passed on its own for the loader path.
    let hw_json = profile.to_json();
    let gpu_layers = profile.gpu_layers.to_string();

    // ── try sidecar first (production builds) ──
    if let Some(sidecar) = sidecar_path(app) {
        let mut cmd = Command::new(&sidecar);
        cmd.args(["--host", "127.0.0.1", "--port", "8000"]);

        // run from the bundle's own folder so its .env (model path) resolves
        if let Some(dir) = sidecar.parent() {
            cmd.current_dir(dir);
        }

        // pass hardware-detected settings to the backend.
        //
        // Deliberately NOT setting THINKSTACK_LLM_MODEL_PATH. We used to force
        // it to a path derived from the current working directory, but the
        // AppImage AppRun chdir's into $APPDIR before launching us, so that
        // resolved to the literal relative string "data/models" and the backend
        // reported "model not found at data/models" -- with the model sitting
        // in the bundle the whole time. The backend resolves this correctly on
        // its own (STATE_DIR/models, seeded from the bundle at startup); a real
        // user-set value still reaches it via apply_inference_env below.
        cmd.env("THINKSTACK_HW_PROFILE", &hw_json);
        cmd.env("THINKSTACK_LLM_GPU_LAYERS", &gpu_layers);
        apply_inference_env(&mut cmd);
        scrub_python_env(&mut cmd);

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        // Capture both streams. Previously they were inherited and thrown away,
        // so a backend that died on import left no trace anywhere -- the only
        // symptom was a spinner that never stopped.
        cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

        if let Ok(child) = cmd.spawn() {
            return Some(child);
        }
    }

    // ── fallback: python venv (development) ──
    let python = python_path();
    let project = project_dir();

    let mut cmd = Command::new(&python);
    cmd.args([
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ])
    .current_dir(&project);

    apply_inference_env(&mut cmd);
    scrub_python_env(&mut cmd);
    // pass hardware-detected settings to the backend (see the sidecar branch
    // for why the model path is left to the backend to resolve)
    cmd.env("THINKSTACK_HW_PROFILE", &hw_json);
    cmd.env("THINKSTACK_LLM_GPU_LAYERS", &gpu_layers);

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());
    cmd.spawn().ok()
}

/// Drain the backend's stdout/stderr into the log file and the loading screen.
///
/// Both streams must be read: a piped stream that nobody drains fills its pipe
/// buffer and blocks the child, which would turn "slow startup" into a genuine
/// deadlock. Returns a handle to the shared tail buffer, so a failure can show
/// the last few lines without the user opening a file.
fn pipe_output(app: &AppHandle, child: &mut Child, started: Instant) -> Arc<Mutex<Vec<String>>> {
    let tail: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    let path = log_path(app);

    let mut streams: Vec<Box<dyn std::io::Read + Send>> = Vec::new();
    if let Some(out) = child.stdout.take() {
        streams.push(Box::new(out));
    }
    if let Some(err) = child.stderr.take() {
        streams.push(Box::new(err));
    }

    for stream in streams {
        let app = app.clone();
        let tail = Arc::clone(&tail);
        let path = path.clone();
        std::thread::spawn(move || {
            let mut file = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&path)
                .ok();
            for line in BufReader::new(stream).lines().map_while(Result::ok) {
                if let Some(f) = file.as_mut() {
                    let _ = writeln!(f, "{line}");
                }
                if let Ok(mut t) = tail.lock() {
                    t.push(line.clone());
                    // keep the buffer bounded; only the last lines are useful
                    if t.len() > 40 {
                        t.remove(0);
                    }
                }
                emit_step(&app, started, "backend", line);
            }
        });
    }
    tail
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

/// Report a terminal startup failure to both the window and the log file.
///
/// Both, deliberately. The window is what the user sees now; the log is what
/// survives them closing it, and a startup failure is precisely the case where
/// they cannot copy anything out of the UI to send us.
fn fail_startup(app: &AppHandle, started: Instant, error: String, tail: Vec<String>) {
    let path = log_path(app);
    emit_step(app, started, "failed", &error);
    let _ = app.emit(
        "startup:failed",
        Failure {
            error,
            log_path: path.display().to_string(),
            tail,
        },
    );
}

/// Diagnose, launch, and wait for the backend, narrating each step to the window.
///
/// Runs on a background thread *after* the window exists. Doing this before the
/// app was built (the previous shape) meant every step happened with nothing
/// listening, so the user saw an undifferentiated spinner no matter which part
/// was slow.
fn boot_backend(app: AppHandle, managed: Arc<Mutex<Option<Child>>>) {
    let started = Instant::now();

    if backend_up() {
        emit_step(
            &app,
            started,
            "ready",
            "Attached to a backend already running",
        );
        let _ = app.emit("startup:ready", ());
        return;
    }

    emit_step(&app, started, "diagnose", "Reading hardware profile");
    let profile = diagnosis::diagnose();
    emit_step(
        &app,
        started,
        "diagnose",
        format!(
            "{:.1} GB RAM ({:.1} GB free), {} threads, {}",
            profile.total_ram_gb,
            profile.available_ram_gb,
            profile.cpu_threads,
            if profile.has_cuda {
                format!("GPU {}", profile.gpu_name)
            } else {
                "CPU only".to_string()
            }
        ),
    );

    // Name the backend we are about to run. When this said "python3 -m uvicorn"
    // inside a packaged build, that alone was the bug: the sidecar lookup had
    // missed the AppImage layout and we were launching a system interpreter the
    // AppRun had already broken.
    match sidecar_path(&app) {
        Some(p) => emit_step(&app, started, "spawn", format!("Backend: {}", p.display())),
        None => emit_step(
            &app,
            started,
            "spawn",
            "No bundled backend found - falling back to a system python (development mode)",
        ),
    }

    emit_step(&app, started, "spawn", "Starting the local engine");
    let Some(mut child) = start_backend(&app, &profile) else {
        let _ = app.emit(
            "startup:failed",
            Failure {
                error: "Could not launch the backend process.".into(),
                log_path: log_path(&app).display().to_string(),
                tail: vec!["The backend binary was not found or could not be executed.".into()],
            },
        );
        return;
    };

    let tail = pipe_output(&app, &mut child, started);
    *managed.lock().unwrap() = Some(child);

    emit_step(&app, started, "wait", "Waiting for the engine to answer");
    while started.elapsed() < STARTUP_TIMEOUT {
        if backend_up() {
            emit_step(&app, started, "ready", "Engine ready");
            let _ = app.emit("startup:ready", ());
            return;
        }
        // A dead child will never open the socket; fail immediately rather than
        // spending the rest of the timeout on a process that already exited.
        if let Ok(mut guard) = managed.lock() {
            if let Some(c) = guard.as_mut() {
                if let Ok(Some(status)) = c.try_wait() {
                    fail_startup(
                        &app,
                        started,
                        format!("The backend exited early ({status})."),
                        tail.lock().map(|t| t.clone()).unwrap_or_default(),
                    );
                    return;
                }
            }
        }
        std::thread::sleep(Duration::from_millis(250));
    }

    fail_startup(
        &app,
        started,
        format!(
            "The engine did not start within {}s.",
            STARTUP_TIMEOUT.as_secs()
        ),
        tail.lock().map(|t| t.clone()).unwrap_or_default(),
    );
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // WebKitGTK's DMABUF renderer corrupts the heap on a range of Linux
    // graphics stacks (Fedora + Mesa here), killing the window a second or two
    // after it paints: "free(): corrupted unsorted chunks". The app had already
    // started the backend and loaded the UI, so this looked like a ThinkStack
    // crash rather than a renderer bug. Disabling it costs a compositing fast
    // path we do not use. Respect an existing value so a user can re-enable it.
    #[cfg(target_os = "linux")]
    {
        if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
            // SAFETY: set before any window or thread that reads the
            // environment exists -- this is the first statement in run().
            unsafe { std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1") };
        }
    }

    // Only manage (and later kill) a backend WE started. If one is already up we
    // attach to it and leave it running on exit.
    let managed: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(None));

    let mut builder = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        // Native file dialog. Bench uses it to let the user point at a .gguf
        // they already have: the UI is served over http, so a webview file
        // input hands back a File with no filesystem path -- and the whole
        // point of importing is to REFERENCE weights where they sit rather
        // than copy several gigabytes through the backend.
        .plugin(tauri_plugin_dialog::init())
        .manage(StartupLog::default())
        .invoke_handler(tauri::generate_handler![startup_log]);

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

    // Boot on a background thread so the window paints immediately and can show
    // progress. The main thread must reach app.run() to pump the event loop; do
    // this work inline and the loading screen never renders at all.
    {
        let handle = app.handle().clone();
        let managed = Arc::clone(&managed);
        std::thread::spawn(move || boot_backend(handle, managed));
    }

    app.run(move |_app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            if let Some(mut child) = managed.lock().unwrap().take() {
                kill_backend(&mut child);
            }
        }
    });
}
