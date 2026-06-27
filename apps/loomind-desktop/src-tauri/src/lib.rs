// Loomind Desktop — Tauri Application
//
// Manages the Experience Engine lifecycle:
// - Finds and spawns engine binary on app start
// - Kills engine on app close
// Uses std::process::Command instead of Tauri sidecar to avoid
// path resolution issues with large PyInstaller binaries.

use tauri::{Emitter, Manager};
use std::sync::Mutex;
use std::process::{Command, Child};
use std::path::PathBuf;

// Hold the engine child process so we can kill it on exit
struct EngineProcess(Mutex<Option<Child>>);

fn find_engine_binary(app: &tauri::App) -> Option<PathBuf> {
    let target_triple = if cfg!(target_os = "windows") {
        "x86_64-pc-windows-msvc"
    } else if cfg!(target_os = "macos") {
        if cfg!(target_arch = "aarch64") { "aarch64-apple-darwin" }
        else { "x86_64-apple-darwin" }
    } else {
        "x86_64-unknown-linux-gnu"
    };

    let ext = if cfg!(target_os = "windows") { ".exe" } else { "" };
    let binary_name = format!("loomind-engine-{}{}", target_triple, ext);

    // Strategy 1: Next to the Tauri executable (production install)
    if let Ok(exe_path) = std::env::current_exe() {
        log::info!("[Loomind] Current exe: {}", exe_path.display());
        if let Some(dir) = exe_path.parent() {
            // Check with target triple (Tauri externalBin convention)
            let candidate = dir.join(&binary_name);
            log::info!("[Loomind] Checking: {}", candidate.display());
            if candidate.exists() {
                return Some(candidate);
            }
            // Check without target triple
            let simple = dir.join(format!("loomind-engine{}", ext));
            log::info!("[Loomind] Checking: {}", simple.display());
            if simple.exists() {
                return Some(simple);
            }
            // Check inside binaries/ subfolder (some installer layouts)
            let in_binaries = dir.join("binaries").join(&binary_name);
            log::info!("[Loomind] Checking: {}", in_binaries.display());
            if in_binaries.exists() {
                return Some(in_binaries);
            }
        }
    }

    // Strategy 2: Tauri resource directory
    if let Ok(resource_dir) = app.path().resource_dir() {
        let candidate = resource_dir.join("binaries").join(&binary_name);
        log::info!("[Loomind] Checking: {}", candidate.display());
        if candidate.exists() {
            return Some(candidate);
        }
    }

    // Strategy 3: src-tauri/binaries (dev mode)
    let dev_candidates = [
        PathBuf::from("src-tauri/binaries").join(&binary_name),
        PathBuf::from("binaries").join(&binary_name),
        // From working directory
        std::env::current_dir().ok().map(|d| d.join("binaries").join(&binary_name)).unwrap_or_default(),
    ];

    for candidate in &dev_candidates {
        log::info!("[Loomind] Checking: {}", candidate.display());
        if candidate.exists() {
            return Some(candidate.clone());
        }
    }

    None
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(EngineProcess(Mutex::new(None)))
        .setup(|app| {
            // ── Logging (enabled in both dev and release) ──
            app.handle().plugin(
                tauri_plugin_log::Builder::default()
                    .level(log::LevelFilter::Info)
                    .build(),
            )?;

            // ── Find and spawn engine binary ──
            match find_engine_binary(app) {
                Some(engine_path) => {
                    log::info!("[Loomind] Found engine at: {}", engine_path.display());

                    match Command::new(&engine_path)
                        .stdout(std::process::Stdio::piped())
                        .stderr(std::process::Stdio::piped())
                        .spawn()
                    {
                        Ok(child) => {
                            log::info!(
                                "[Loomind] Engine spawned (PID: {})",
                                child.id()
                            );

                            // Store child for cleanup
                            let engine_state = app.state::<EngineProcess>();
                            *engine_state.0.lock().unwrap() = Some(child);

                            // Emit event so frontend knows to start polling
                            let _ = app.handle().emit("engine-spawned", true);
                        }
                        Err(e) => {
                            log::error!(
                                "[Loomind] Failed to spawn engine: {}",
                                e
                            );
                            log::info!(
                                "[Loomind] Start engine manually: python -m uvicorn src.main:app --port 8082"
                            );
                        }
                    }
                }
                None => {
                    log::warn!("[Loomind] Engine binary not found in any search path");
                    log::info!("[Loomind] Running in standalone UI mode (connect to external engine)");
                }
            }

            Ok(())
        })
        // ── Kill engine on app exit ──
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let app = window.app_handle();
                let engine_state = app.state::<EngineProcess>();
                let mut guard = engine_state.0.lock().unwrap();
                if let Some(mut child) = guard.take() {
                    log::info!("[Loomind] Killing engine (PID: {})...", child.id());
                    let _ = child.kill();
                    let _ = child.wait(); // Prevent zombie process
                    log::info!("[Loomind] Engine killed.");
                }
                drop(guard);
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Loomind application");
}
