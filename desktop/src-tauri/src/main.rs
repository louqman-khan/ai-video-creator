// The desktop app: a native window around the local server. It starts `avc app` on a free port, shows a loading page until the server answers,
// then shows the editor; closing the window stops the server. Same code for macOS, Windows and Linux.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend;

use backend::Backend;
use tauri::{Manager, RunEvent, WebviewWindow};

fn show(window: &WebviewWindow, result: Result<String, String>) {
    match result {
        Ok(url) => {
            let _ = window.eval(&format!("window.location.replace({:?})", url));
        }
        Err(message) => {
            let json = format!("{:?}", message); // a Rust string literal is also a valid JavaScript string literal for this text
            let _ = window.eval(&format!("window.showStartError({})", json));
        }
    }
}

fn main() {
    let app = tauri::Builder::default()
        .manage(Backend::default())
        .setup(|app| {
            let window = app.get_webview_window("main").expect("the main window exists");
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let resources = handle.path().resource_dir().ok().map(|d| d.join("resources")).filter(|d| d.is_dir()).or_else(|| handle.path().resource_dir().ok());
                let data = handle.path().app_data_dir().ok();
                let result = backend::start(handle.state::<Backend>().inner(), resources, data);
                show(&window, result);
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("could not build the desktop app");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            backend::stop(handle.state::<Backend>().inner());
        }
    });
}
