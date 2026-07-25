// Startup hardware diagnosis.
//
// Runs once, in the Tauri shell, BEFORE the Python backend is spawned, and hands
// the result to the backend as a JSON env var (THINKSTACK_HW_PROFILE). Doing it
// here — in native Rust — is deliberate: the old path made Python `import torch`
// and call `torch.cuda.is_available()` just to size the model, which is slow
// (torch import) and can stall for seconds on a half-broken CUDA driver. Reading
// RAM/CPU natively and probing the GPU with a *timeout* makes the whole thing
// sub-100ms and never hangs, so the loading screen is not held hostage by it.
//
// Everything degrades to a safe CPU-only profile: any probe that errors or times
// out simply lowers the tier, it never fails the launch.

use serde_json::json;
use std::process::Command;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

/// A snapshot of the machine's compute resources and the loading decision
/// derived from it. Mirrors the Python `HardwareProfile` so the backend can
/// rebuild it verbatim from the JSON without re-detecting anything.
#[derive(Debug, Clone)]
pub struct HwProfile {
    pub total_ram_gb: f64,
    /// Free RAM *at launch* — the budget the model must fit into leaves headroom
    /// on top of this, on the assumption the user has other apps running.
    pub available_ram_gb: f64,
    pub cpu_threads: usize,
    pub gpu_name: String,
    pub gpu_vendor: String, // "nvidia" | "apple" | "none"
    pub vram_gb: f64,
    pub has_cuda: bool,
    pub tier: String, // "low" | "medium" | "high"
    /// -1 = offer full GPU offload (the backend refines this against the model
    /// size), 0 = CPU-only. Only ever -1 when a CUDA GPU with usable VRAM exists.
    pub gpu_layers: i32,
}

impl HwProfile {
    /// Serialize to the JSON the backend parses out of THINKSTACK_HW_PROFILE.
    pub fn to_json(&self) -> String {
        json!({
            "source": "rust",
            "total_ram_gb": round1(self.total_ram_gb),
            "available_ram_gb": round1(self.available_ram_gb),
            "cpu_threads": self.cpu_threads,
            "cpu_cores": self.cpu_threads,
            "gpu_name": self.gpu_name,
            "gpu_vendor": self.gpu_vendor,
            "vram_gb": round1(self.vram_gb),
            "has_cuda": self.has_cuda,
            "tier": self.tier,
            "gpu_layers": self.gpu_layers,
        })
        .to_string()
    }
}

fn round1(v: f64) -> f64 {
    (v * 10.0).round() / 10.0
}

/// Run the full diagnosis. Never panics; the worst case is an all-zero,
/// CPU-only, "low" tier profile that still runs the app.
pub fn diagnose() -> HwProfile {
    let (total_ram_gb, available_ram_gb) = detect_ram();
    let cpu_threads = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);
    let (gpu_name, gpu_vendor, vram_gb, has_cuda) = detect_gpu();
    let tier = classify_tier(total_ram_gb, vram_gb);

    // full offload is only offered for a CUDA GPU with usable VRAM; the frozen
    // llama.cpp is the CPU build unless the machine has CUDA, so anything else
    // (including Apple Metal, which we still *report* for accuracy) stays CPU to
    // avoid a hard crash at model load. the backend narrows -1 to a real layer
    // count against the actual model size.
    let gpu_layers = if has_cuda && vram_gb >= 2.0 { -1 } else { 0 };

    HwProfile {
        total_ram_gb,
        available_ram_gb,
        cpu_threads,
        gpu_name,
        gpu_vendor,
        vram_gb,
        has_cuda,
        tier,
        gpu_layers,
    }
}

/// (total_gb, available_gb) via sysinfo. Returns (0,0) if it somehow fails,
/// which classify_tier treats as the low tier.
fn detect_ram() -> (f64, f64) {
    use sysinfo::System;
    let mut sys = System::new();
    sys.refresh_memory();
    // sysinfo >= 0.30 reports memory in bytes.
    let to_gb = |b: u64| b as f64 / 1024.0 / 1024.0 / 1024.0;
    (to_gb(sys.total_memory()), to_gb(sys.available_memory()))
}

/// (name, vendor, vram_gb, has_cuda). CPU-safe default is ("", "none", 0, false).
fn detect_gpu() -> (String, String, f64, bool) {
    // NVIDIA: authoritative and gives real VRAM, but nvidia-smi can hang on a
    // broken driver, so it runs under a 2s timeout.
    if let Some(out) = nvidia_query(Duration::from_secs(2)) {
        // "<name>, <mem_total_mib>"
        let line = out.lines().next().unwrap_or("").trim().to_string();
        if let Some((name, mem)) = line.rsplit_once(',') {
            if let Ok(mib) = mem.trim().parse::<f64>() {
                return (
                    name.trim().to_string(),
                    "nvidia".to_string(),
                    mib / 1024.0,
                    true,
                );
            }
        }
    }

    // Apple Silicon: report Metal for an accurate profile. VRAM is left 0 and
    // has_cuda false, so the loader stays CPU-only (see gpu_layers note above)
    // until a Metal-enabled llama.cpp build is validated end to end.
    #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
    {
        return (
            "Apple Silicon (Metal)".to_string(),
            "apple".to_string(),
            0.0,
            false,
        );
    }

    #[allow(unreachable_code)]
    (String::new(), "none".to_string(), 0.0, false)
}

/// Query nvidia-smi on a background thread and give up after `timeout`.
/// Returns the stdout on success, None on timeout / missing tool / failure.
fn nvidia_query(timeout: Duration) -> Option<String> {
    let (tx, rx) = mpsc::channel();
    thread::spawn(move || {
        let out = Command::new("nvidia-smi")
            .args([
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ])
            .output();
        // the receiver may already be gone (timed out); ignore the send error.
        let _ = tx.send(out);
    });
    match rx.recv_timeout(timeout) {
        Ok(Ok(out)) if out.status.success() => String::from_utf8(out.stdout).ok(),
        _ => None,
    }
}

/// Same thresholds as the Python `_classify_tier`, kept in sync deliberately so
/// the env-provided tier matches what the backend would have computed itself.
fn classify_tier(total_ram_gb: f64, vram_gb: f64) -> String {
    if vram_gb > 8.0 || total_ram_gb > 24.0 {
        "high".to_string()
    } else if vram_gb >= 2.0 || total_ram_gb >= 12.0 {
        "medium".to_string()
    } else {
        "low".to_string()
    }
}
