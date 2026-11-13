use std::process::Stdio;
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};

use tokio::sync::mpsc;
use tokio::time::timeout;
use tracing::{debug, error, info, warn};

/// Python 子进程管理器
pub struct PythonProcess {
    child: Option<Child>,
    child_id: Option<u32>,
    tx: Option<mpsc::UnboundedSender<String>>,
    response_tx: Option<mpsc::UnboundedSender<String>>,
}

impl PythonProcess {
    pub fn new() -> Self {
        Self {
            child: None,
            child_id: None,
            tx: None,
            response_tx: None,
        }
    }

    /// 设置响应通道，stdout 读取到的 JSON Lines 会通过此通道发送
    pub fn set_response_sender(&mut self, sender: mpsc::UnboundedSender<String>) {
        self.response_tx = Some(sender);
    }

    /// 启动后端子进程（生产模式优先，回退到开发模式）
    pub async fn start(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        // 生产模式：查找可执行文件同级目录下的 backend/gudashi-backend
        let exe_dir = std::env::current_exe()?
            .parent()
            .ok_or("无法获取可执行文件目录")?
            .to_path_buf();
        let prod_name = if cfg!(target_os = "windows") {
            "gudashi-backend.exe"
        } else {
            "gudashi-backend"
        };
        let prod_path = exe_dir.join("backend").join(prod_name);

        let mut child;
        if prod_path.exists() {
            // 生产模式：直接运行 PyInstaller 打包产物
            // CREATE_NO_WINDOW(0x08000000)：不弹出后端控制台窗口，仅保留管道通信
            let mut cmd = Command::new(&prod_path);
            cmd.stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
            #[cfg(target_os = "windows")]
            cmd.creation_flags(0x08000000);
            child = cmd.spawn()?;
            info!(action = "backend_spawn", mode = "production", path = ?prod_path, "Production backend started");
        } else if let Some(backend_main) = resolve_dev_backend(&exe_dir) {
            // 开发模式：优先使用后端自带 venv 解释器，工作目录设为 backend 目录
            let backend_dir = backend_main
                .parent()
                .ok_or("无法获取后端目录")?
                .to_path_buf();
            let venv_python = if cfg!(target_os = "windows") {
                backend_dir.join(".venv").join("Scripts").join("python.exe")
            } else {
                backend_dir.join(".venv").join("bin").join("python")
            };
            let (python_cmd, python_desc): (std::path::PathBuf, String) = if venv_python.exists() {
                (venv_python.clone(), venv_python.display().to_string())
            } else if cfg!(target_os = "windows") {
                (std::path::PathBuf::from("python"), "python".to_string())
            } else {
                (std::path::PathBuf::from("python3"), "python3".to_string())
            };
            let mut dev_cmd = Command::new(&python_cmd);
            dev_cmd
                .arg(&backend_main)
                .current_dir(&backend_dir)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
            #[cfg(target_os = "windows")]
            dev_cmd.creation_flags(0x08000000);
            child = dev_cmd.spawn()?;
            info!(
                action = "backend_spawn",
                mode = "development",
                python = %python_desc,
                backend_dir = ?backend_dir,
                "Development backend started"
            );
        } else {
            return Err(format!(
                "未找到后端。生产模式需要 {}；开发模式从 exe 目录({})与工作目录逐级向上探测 */backend/main.py（也可用环境变量 GUDASHI_BACKEND_DIR 显式指定后端目录）",
                prod_path.display(),
                exe_dir.display()
            ).into());
        }

        // 记录 PID，用于退出时强制终止
        self.child_id = child.id();

        let stdout = child
            .stdout
            .take()
            .ok_or("Failed to capture stdout")?;
        let stdin = child
            .stdin
            .take()
            .ok_or("Failed to capture stdin")?;
        let stderr = child
            .stderr
            .take()
            .ok_or("Failed to capture stderr")?;

        // 创建通信通道
        let (tx, mut rx) = mpsc::unbounded_channel::<String>();
        self.tx = Some(tx.clone());

        // 启动写入任务：将 channel 中的消息写入 Python stdin
        tokio::spawn(async move {
            use tokio::io::AsyncWriteExt;
            let mut stdin = stdin;
            while let Some(line) = rx.recv().await {
                if let Err(e) = stdin.write_all(line.as_bytes()).await {
                    error!(action = "python_stdin_write", error = %e);
                    break;
                }
                if let Err(e) = stdin.write_all(b"\n").await {
                    error!(action = "python_stdin_write", error = %e);
                    break;
                }
            }
        });

        // 启动读取任务：从 Python stdout 读取 JSON Lines，通过 response_tx 传递
        // 关键修复：不用 lines()（遇无效 UTF-8 会返回 Err 退出循环，导致后续响应全丢），
        // 改用 read_until(b'\n') 按字节读取 + from_utf8_lossy 容错，单条损坏不影响后续。
        let response_tx = self.response_tx.clone();
        tokio::spawn(async move {
            use tokio::io::AsyncBufReadExt;
            let mut reader = BufReader::new(stdout);
            let mut buf: Vec<u8> = Vec::with_capacity(4096);

            loop {
                buf.clear();
                match reader.read_until(b'\n', &mut buf).await {
                    Ok(0) => break, // EOF：后端 stdout 关闭（进程退出）
                    Ok(_n) => {
                        while buf.last() == Some(&b'\n') || buf.last() == Some(&b'\r') {
                            buf.pop();
                        }
                        if buf.is_empty() {
                            continue;
                        }
                        let line = String::from_utf8_lossy(&buf).into_owned();
                        debug!(action = "python_stdout", line = %line);
                        if let Some(tx) = &response_tx {
                            let _ = tx.send(line);
                        }
                    }
                    Err(e) => {
                        warn!(action = "python_stdout_read_error", error = %e, "stdout read error, continuing");
                        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
                    }
                }
            }

            warn!(action = "python_stdout_eof", "Python stdout stream ended");
        });

        // 启动 stderr 读取任务：持续消费 stderr 防止管道写满阻塞子进程，并记录日志
        tokio::spawn(async move {
            let reader = BufReader::new(stderr);
            let mut lines = reader.lines();

            while let Ok(Some(line)) = lines.next_line().await {
                if line.trim().is_empty() {
                    continue;
                }
                warn!(action = "python_stderr", line = %line);
            }
        });

        self.child = Some(child);
        info!(action = "python_spawn", pid = ?self.child_id, "Python subprocess started");
        Ok(())
    }

    /// 停止 Python 子进程
    /// 先发送终止信号，等待最多 3 秒；超时则强制终止
    pub async fn stop(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        let child_id = self.child_id.take();
        if let Some(mut child) = self.child.take() {
            // 1. 发送终止信号
            if let Err(e) = child.kill().await {
                warn!(action = "python_kill_signal", error = %e);
            }

            // 2. 等待进程退出，最多 3 秒
            match timeout(Duration::from_secs(3), child.wait()).await {
                Ok(Ok(status)) => {
                    info!(action = "python_stop", pid = ?child_id, status = ?status, "Python subprocess exited cleanly");
                }
                Ok(Err(e)) => {
                    warn!(action = "python_wait_err", pid = ?child_id, error = %e);
                }
                Err(_) => {
                    warn!(action = "python_stop_timeout", pid = ?child_id, "Python subprocess did not exit within 3s, forcing termination");
                    // 3. 超时后按 PID 强制终止
                    if let Some(id) = child_id {
                        #[cfg(target_os = "windows")]
                        {
                            let _ = std::process::Command::new("taskkill")
                                .args(["/F", "/T", "/PID", &id.to_string()])
                                .output();
                        }
                        #[cfg(not(target_os = "windows"))]
                        {
                            let _ = std::process::Command::new("kill")
                                .args(["-9", &id.to_string()])
                                .output();
                        }
                    }
                }
            }
        }
        self.tx = None;
        self.response_tx = None;
        Ok(())
    }

    /// 检查进程是否仍在运行
    pub fn is_running(&self) -> bool {
        self.child.as_ref().map_or(false, |c| c.id().is_some())
    }

    /// 获取后端进程 PID（用于外部诊断）
    pub fn pid(&self) -> Option<u32> {
        self.child_id
    }

    /// 获取 stdin 写入通道（用于 bridge attach_sender）
    pub fn get_sender(&self) -> Option<mpsc::UnboundedSender<String>> {
        self.tx.clone()
    }
}

/// 开发模式后端探测：
/// 1. 环境变量 GUDASHI_BACKEND_DIR 显式指定的目录下的 main.py
/// 2. 从 exe 目录与当前工作目录逐级向上，查找 backend/main.py 或 <任意子目录>/backend/main.py
///    （兼容「股大师后端v1.3_联调修复版/backend」这类与前端并列的后端目录布局，
///      无论是 C 盘源码树还是 D 盘集中编译缓存的 target/debug 目录均可命中）
fn resolve_dev_backend(exe_dir: &std::path::Path) -> Option<std::path::PathBuf> {
    // 1. 环境变量显式指定
    if let Ok(dir) = std::env::var("GUDASHI_BACKEND_DIR") {
        let p = std::path::Path::new(&dir).join("main.py");
        if p.exists() {
            return Some(p);
        }
        warn!(action = "resolve_dev_backend", dir = %dir, "GUDASHI_BACKEND_DIR 下未找到 main.py，继续自动探测");
    }

    // 2. 收集候选根：exe 目录的祖先链 + 工作目录的祖先链
    let mut roots: Vec<std::path::PathBuf> = Vec::new();
    let mut cur = Some(exe_dir.to_path_buf());
    while let Some(d) = cur {
        roots.push(d.clone());
        cur = d.parent().map(|p| p.to_path_buf());
    }
    if let Ok(cwd) = std::env::current_dir() {
        let mut cur = Some(cwd);
        while let Some(d) = cur {
            roots.push(d.clone());
            cur = d.parent().map(|p| p.to_path_buf());
        }
    }

    // 3. 逐个根探测：backend/main.py 或 <子目录>/backend/main.py
    for root in &roots {
        let direct = root.join("backend").join("main.py");
        if direct.is_file() {
            return Some(direct);
        }
        if let Ok(entries) = std::fs::read_dir(root) {
            for entry in entries.flatten() {
                let cand = entry.path().join("backend").join("main.py");
                if cand.is_file() {
                    return Some(cand);
                }
            }
        }
    }

    warn!(action = "resolve_dev_backend", roots = ?roots, "开发模式后端探测失败");
    None
}
