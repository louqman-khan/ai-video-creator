//! Starting and stopping the Python server (`avc app`) that sits behind the window. Written to work the same on macOS, Windows and Linux.

use std::fs::{self, File};
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

/// The running server process (None until it has been started and after it has been stopped).
#[derive(Default)]
pub struct Backend {
    pub child: Mutex<Option<Child>>,
}

/// The project folder: `AVC_HOME`, or the nearest folder above the program that contains `backend/pyproject.toml`, or where this shell was built.
pub fn project_root() -> PathBuf {
    if let Ok(home) = std::env::var("AVC_HOME") {
        return PathBuf::from(home);
    }
    if let Ok(exe) = std::env::current_exe() {
        for dir in exe.ancestors().skip(1) {
            if dir.join("backend").join("pyproject.toml").is_file() {
                return dir.to_path_buf();
            }
        }
    }
    Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("..")
}

/// The `avc` program: `AVC_BIN`, or the project's virtual environment (`.venv/bin/avc` or `.venv\Scripts\avc.exe`), or `avc` on PATH.
pub fn avc_program(root: &Path) -> PathBuf {
    if let Ok(bin) = std::env::var("AVC_BIN") {
        return PathBuf::from(bin);
    }
    let candidates = [root.join(".venv").join("Scripts").join("avc.exe"), root.join(".venv").join("bin").join("avc")];
    candidates.into_iter().find(|p| p.is_file()).unwrap_or_else(|| PathBuf::from("avc"))
}

/// A free local port.
pub fn free_port() -> std::io::Result<u16> {
    Ok(TcpListener::bind("127.0.0.1:0")?.local_addr()?.port())
}

/// True when the server answers `GET /api/health` with 200.
pub fn healthy(port: u16) -> bool {
    let Ok(mut s) = TcpStream::connect_timeout(&([127, 0, 0, 1], port).into(), Duration::from_millis(300)) else { return false };
    let _ = s.set_read_timeout(Some(Duration::from_millis(800)));
    if s.write_all(b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n").is_err() {
        return false;
    }
    let mut head = [0u8; 16];
    s.read(&mut head).map(|n| head[..n].starts_with(b"HTTP/1.1 200")).unwrap_or(false)
}

fn tail(path: &Path, lines: usize) -> String {
    let text = fs::read_to_string(path).unwrap_or_default();
    let all: Vec<&str> = text.lines().collect();
    all[all.len().saturating_sub(lines)..].join("\n")
}

/// Starts the server and waits until it answers. Returns the URL to show, or a message that explains what went wrong.
pub fn start(backend: &Backend) -> Result<String, String> {
    let root = project_root();
    let program = avc_program(&root);
    let port = free_port().map_err(|e| format!("No free port on this computer: {e}"))?;
    let work = root.join("work");
    let _ = fs::create_dir_all(&work);
    let log_path = work.join("desktop.log");
    let log = File::create(&log_path).map_err(|e| format!("Cannot write {}: {e}", log_path.display()))?;
    let log_err = log.try_clone().map_err(|e| e.to_string())?;

    let mut cmd = Command::new(&program);
    cmd.args(["app", "--no-browser", "--port", &port.to_string()])
        .current_dir(&root)
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .env("AVC_PARENT_PID", std::process::id().to_string()) // the server stops by itself when this program is gone
        .stdin(Stdio::null())
        .stdout(Stdio::from(log))
        .stderr(Stdio::from(log_err));
    #[cfg(windows)]
    cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: no black console window next to the app (its helper programs inherit this)

    let child = cmd.spawn().map_err(|e| {
        format!(
            "Could not start the server ({}): {e}\n\nSet AVC_HOME to the project folder (the one with backend/ and .venv/), or AVC_BIN to the avc program.",
            program.display()
        )
    })?;
    *backend.child.lock().unwrap() = Some(child);

    let started = Instant::now();
    while started.elapsed() < Duration::from_secs(120) {
        if healthy(port) {
            return Ok(format!("http://127.0.0.1:{port}/"));
        }
        if let Some(child) = backend.child.lock().unwrap().as_mut() {
            if let Ok(Some(status)) = child.try_wait() {
                return Err(format!("The server stopped right after starting ({status}).\n\n{}", tail(&log_path, 15)));
            }
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    Err(format!("The server did not answer within two minutes.\n\n{}", tail(&log_path, 15)))
}

/// Stops the server and anything it started (ffmpeg and friends).
pub fn stop(backend: &Backend) {
    if let Some(mut child) = backend.child.lock().unwrap().take() {
        #[cfg(windows)]
        {
            let _ = Command::new("taskkill").args(["/PID", &child.id().to_string(), "/T", "/F"]).creation_flags(0x0800_0000).status();
        }
        #[cfg(not(windows))]
        {
            let _ = child.kill();
        }
        let _ = child.wait();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_free_port_is_found_and_nothing_answers_there() {
        let p = free_port().unwrap();
        assert!(p > 0 && !healthy(p));
    }

    #[test]
    fn the_health_check_recognises_a_healthy_server_only() {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = l.local_addr().unwrap().port();
        let t = std::thread::spawn(move || {
            for (i, s) in l.incoming().take(2).enumerate() {
                let mut s = s.unwrap();
                let mut buf = [0u8; 256];
                let _ = s.read(&mut buf);
                let _ = s.write_all(if i == 0 { b"HTTP/1.1 200 OK\r\n\r\n{}" as &[u8] } else { b"HTTP/1.1 500 Oops\r\n\r\n" });
            }
        });
        assert!(healthy(port));
        assert!(!healthy(port));
        t.join().unwrap();
    }

    #[test]
    fn the_program_falls_back_to_avc_on_path() {
        let nothing = std::env::temp_dir().join("avc-no-such-project");
        if std::env::var("AVC_BIN").is_err() {
            assert_eq!(avc_program(&nothing), PathBuf::from("avc"));
        }
    }
}
