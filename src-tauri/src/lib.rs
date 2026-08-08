mod commands;

use commands::conversion::{cancel_batch, get_queue_status, start_conversion_batch, ConversionQueue};
use commands::health::check_system_health;
use commands::tools::resolve_conversion_tool;
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager,
    WindowEvent,
};

pub fn run() {
    let builder = tauri::Builder::default()
        .manage(ConversionQueue::default())
        .invoke_handler(tauri::generate_handler![
            check_system_health,
            resolve_conversion_tool,
            start_conversion_batch,
            cancel_batch,
            get_queue_status
        ])
        .setup(|app| {
            let show_item = MenuItem::with_id(app, "show", "Show window", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

            TrayIconBuilder::with_id("main-tray")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .tooltip("PDF & Document Converter")
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;

            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        });

    if let Err(error) = builder.run(tauri::generate_context!()) {
        eprintln!("application error: {error}");
    }
}
