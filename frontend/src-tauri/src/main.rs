// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use gudashi_lib::run;

fn main() {
    // 初始化 tracing 日志
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .init();

    tracing::info!(action = "app_start", "Gudashi starting...");

    if let Err(e) = run() {
        tracing::error!(action = "app_fatal", error = %e, "Application failed to start");
        std::process::exit(1);
    }
}
