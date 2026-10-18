//! MCP acceptance client for `photocraft-cli mcp` over stdio.
//!
//! Usage: photocraft-mcp-check CLI WORKDIR REPORT [TRANSCRIPT]
//!
//! Starts `CLI mcp --automation-read-root WORKDIR --automation-write-root WORKDIR` with piped
//! standard streams and speaks MCP (newline-delimited JSON-RPC 2.0) to it: the initialize
//! handshake, tools/list, real tools/call requests that create, edit, save and reopen a
//! document, tool errors, a malformed line, a request written in fragments, two requests in
//! flight at once, end of input, and three further short sessions. Every check is written to
//! REPORT as it completes (`CHECK <name> PASS|FAIL <detail>`), then `SUMMARY`. All traffic goes
//! to TRANSCRIPT. The exit status is 0 only when every check passed.
//!
//! Reading: the server's stdout is read one byte per call on a separate thread. An AROS PIPE:
//! read returns only when the requested length has arrived or the writer closed, so a buffered
//! read would wait for kilobytes the server never sends. Child::kill is not available on AROS,
//! so a wedged server cannot be stopped from here; the checks have timeouts and the report says
//! what was still pending, and the external supervisor powers the machine off.

use std::io::{Read, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{Receiver, RecvTimeoutError, channel};
use std::time::{Duration, Instant};

use serde_json::{Value, json};

const REPLY_TIMEOUT: Duration = Duration::from_secs(120);
const EXIT_TIMEOUT: Duration = Duration::from_secs(60);

struct Log {
    report: std::fs::File,
    transcript: Option<std::fs::File>,
    pass: u32,
    fail: u32,
}

impl Log {
    fn check(&mut self, name: &str, ok: bool, detail: &str) {
        if ok {
            self.pass += 1;
        } else {
            self.fail += 1;
        }
        let detail = detail.replace('\n', " ");
        let _ = writeln!(self.report, "CHECK {name} {} {detail}", if ok { "PASS" } else { "FAIL" });
        let _ = self.report.flush();
    }

    fn note(&mut self, text: &str) {
        let _ = writeln!(self.report, "NOTE {}", text.replace('\n', " "));
        let _ = self.report.flush();
    }

    fn traffic(&mut self, dir: &str, text: &str) {
        if let Some(t) = self.transcript.as_mut() {
            let shown: String = text.chars().take(4000).collect();
            let _ = writeln!(t, "{dir} {shown}");
            let _ = t.flush();
        }
    }
}

struct Session {
    child: Child,
    stdin: Option<ChildStdin>,
    lines: Receiver<Option<String>>,
    stderr: std::thread::JoinHandle<Vec<u8>>,
    stdout_reader: std::thread::JoinHandle<()>,
    next_id: u64,
    started: Instant,
}

fn bytewise_lines(mut source: impl Read + Send + 'static) -> (Receiver<Option<String>>, std::thread::JoinHandle<()>) {
    let (tx, rx) = channel();
    let handle = std::thread::spawn(move || {
        let mut line = Vec::new();
        let mut byte = [0u8; 1];
        loop {
            match source.read(&mut byte) {
                Ok(0) | Err(_) => {
                    if !line.is_empty() {
                        let _ = tx.send(Some(String::from_utf8_lossy(&line).into_owned()));
                    }
                    let _ = tx.send(None);
                    return;
                }
                Ok(_) if byte[0] == b'\n' => {
                    let _ = tx.send(Some(String::from_utf8_lossy(&line).into_owned()));
                    line.clear();
                }
                Ok(_) => line.push(byte[0]),
            }
        }
    });
    (rx, handle)
}

impl Session {
    fn start(cli: &str, workdir: &str) -> std::io::Result<Self> {
        let mut child = Command::new(cli)
            .args(["mcp", "--automation-read-root", workdir, "--automation-write-root", workdir])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;
        let stdin = child.stdin.take();
        let stdout = child.stdout.take().ok_or_else(|| std::io::Error::other("no stdout pipe"))?;
        let mut stderr = child.stderr.take().ok_or_else(|| std::io::Error::other("no stderr pipe"))?;
        let (lines, stdout_reader) = bytewise_lines(stdout);
        let stderr = std::thread::spawn(move || {
            let mut all = Vec::new();
            let mut byte = [0u8; 1];
            while let Ok(1) = stderr.read(&mut byte) {
                all.push(byte[0]);
            }
            all
        });
        Ok(Session { child, stdin, lines, stderr, stdout_reader, next_id: 1, started: Instant::now() })
    }

    fn write_raw(&mut self, log: &mut Log, bytes: &[u8]) -> std::io::Result<()> {
        log.traffic(">", String::from_utf8_lossy(bytes).trim_end());
        let stdin = self.stdin.as_mut().ok_or_else(|| std::io::Error::other("stdin closed"))?;
        stdin.write_all(bytes)?;
        stdin.flush()
    }

    fn send(&mut self, log: &mut Log, message: &Value) -> std::io::Result<()> {
        let mut text = message.to_string();
        text.push('\n');
        self.write_raw(log, text.as_bytes())
    }

    fn request(&mut self, log: &mut Log, method: &str, params: Value) -> std::io::Result<u64> {
        let id = self.next_id;
        self.next_id += 1;
        self.send(log, &json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params}))?;
        Ok(id)
    }

    /// The next message from the server (any kind), or why there was none.
    fn next(&mut self, log: &mut Log, timeout: Duration) -> Result<Value, String> {
        let deadline = Instant::now() + timeout;
        loop {
            let left = deadline.saturating_duration_since(Instant::now());
            match self.lines.recv_timeout(left) {
                Ok(Some(line)) => {
                    log.traffic("<", &line);
                    if line.trim().is_empty() {
                        continue;
                    }
                    return serde_json::from_str(&line).map_err(|e| format!("server wrote a non-JSON line ({e}): {line}"));
                }
                Ok(None) => return Err("server closed its output".into()),
                Err(RecvTimeoutError::Timeout) => return Err(format!("no message within {timeout:?}")),
                Err(RecvTimeoutError::Disconnected) => return Err("server output reader ended".into()),
            }
        }
    }

    /// The response to `id`; server notifications in between are skipped (logged).
    fn response(&mut self, log: &mut Log, id: u64) -> Result<Value, String> {
        let deadline = Instant::now() + REPLY_TIMEOUT;
        loop {
            let v = self.next(log, deadline.saturating_duration_since(Instant::now()))?;
            if v.get("id").and_then(Value::as_u64) == Some(id) {
                return Ok(v);
            }
            if v.get("id").is_some() && v.get("method").is_none() {
                return Err(format!("response for an unexpected id: {v}"));
            }
        }
    }

    fn call(&mut self, log: &mut Log, method: &str, params: Value) -> Result<Value, String> {
        let id = self.request(log, method, params).map_err(|e| format!("write failed: {e}"))?;
        self.response(log, id)
    }

    fn tool(&mut self, log: &mut Log, name: &str, arguments: Value) -> Result<Value, String> {
        let v = self.call(log, "tools/call", json!({"name": name, "arguments": arguments}))?;
        v.get("result").cloned().ok_or_else(|| format!("no result: {v}"))
    }

    /// Close the server's input and wait (bounded) for it to exit. Returns the exit code.
    fn finish(mut self, log: &mut Log) -> Result<(i32, String, Duration), String> {
        drop(self.stdin.take());
        let deadline = Instant::now() + EXIT_TIMEOUT;
        loop {
            match self.child.try_wait() {
                Ok(Some(status)) => {
                    let stderr = self.stderr.join().unwrap_or_default();
                    let _ = self.stdout_reader.join();
                    // Anything the server wrote after the last response.
                    while let Ok(Some(line)) = self.lines.try_recv() {
                        log.traffic("< (late)", &line);
                    }
                    return Ok((status.code().unwrap_or(-1), String::from_utf8_lossy(&stderr).into_owned(), self.started.elapsed()));
                }
                Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(100)),
                Ok(None) => return Err(format!("server still running {EXIT_TIMEOUT:?} after end of input")),
                Err(e) => return Err(format!("try_wait: {e}")),
            }
        }
    }
}

fn text_of(result: &Value) -> String {
    result
        .get("content")
        .and_then(Value::as_array)
        .map(|c| c.iter().filter_map(|x| x.get("text").and_then(Value::as_str)).collect::<Vec<_>>().join(" "))
        .unwrap_or_default()
}

fn is_error(result: &Value) -> bool {
    result.get("isError").and_then(Value::as_bool) == Some(true)
}

fn initialize(s: &mut Session, log: &mut Log, name: &str) -> bool {
    let r = s.call(
        log,
        "initialize",
        json!({"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "photocraft-mcp-check", "version": "0.1.0"}}),
    );
    let ok = match &r {
        Ok(v) => {
            let result = v.get("result");
            let server = result.and_then(|r| r.get("serverInfo")).cloned().unwrap_or(Value::Null);
            let version = result.and_then(|r| r.get("protocolVersion")).cloned().unwrap_or(Value::Null);
            let tools = result.and_then(|r| r.pointer("/capabilities/tools")).is_some();
            log.check(name, server.is_object() && version.is_string() && tools, &format!("serverInfo={server} protocolVersion={version} tools={tools}"));
            server.is_object()
        }
        Err(e) => {
            log.check(name, false, e);
            false
        }
    };
    if ok {
        let sent = s.send(log, &json!({"jsonrpc": "2.0", "method": "notifications/initialized"}));
        log.check(&format!("{name}-initialized"), sent.is_ok(), "notifications/initialized sent");
    }
    ok
}

fn main_session(cli: &str, workdir: &str, log: &mut Log) {
    let mut s = match Session::start(cli, workdir) {
        Ok(s) => s,
        Err(e) => return log.check("spawn", false, &e.to_string()),
    };
    log.check("spawn", true, cli);
    if !initialize(&mut s, log, "initialize") {
        match s.finish(log) {
            Ok((code, stderr, _)) => log.note(&format!("server exit {code}, stderr: {stderr}")),
            Err(e) => log.note(&e),
        }
        return;
    }

    // tools/list
    match s.call(log, "tools/list", json!({})) {
        Ok(v) => {
            let names: Vec<String> = v
                .pointer("/result/tools")
                .and_then(Value::as_array)
                .map(|t| t.iter().filter_map(|x| x.get("name").and_then(Value::as_str).map(str::to_string)).collect())
                .unwrap_or_default();
            let needed = ["doc_new", "doc_open", "doc_save", "doc_inspect", "command_run", "command_list", "render_preview", "session_list"];
            let missing: Vec<&str> = needed.iter().copied().filter(|n| !names.iter().any(|x| x == n)).collect();
            log.check("tools-list", missing.is_empty(), &format!("{} tools; missing {missing:?}", names.len()));
        }
        Err(e) => log.check("tools-list", false, &e),
    }

    // A malformed line gets a parse error with id null; the session keeps working.
    let _ = s.write_raw(log, b"{this is not json\n");
    match s.next(log, REPLY_TIMEOUT) {
        Ok(v) => {
            let code = v.pointer("/error/code").and_then(Value::as_i64);
            log.check("malformed-line", code == Some(-32700) && v.get("id") == Some(&Value::Null), &v.to_string());
        }
        Err(e) => log.check("malformed-line", false, &e),
    }

    // A real edit: new document, a new layer, a filled rectangle.
    let steps: Vec<(&str, &str, Value)> = vec![
        ("doc-new", "doc_new", json!({"width": 64, "height": 48})),
        ("layer-new", "command_run", json!({"id": "layer.new.layer", "params": {"name": "red box"}})),
        ("select-rect", "command_run", json!({"id": "select.rect", "params": {"x": 10, "y": 8, "width": 20, "height": 16}})),
        ("fill", "command_run", json!({"id": "edit.fill", "params": {"color": "#ff0000"}})),
        ("deselect", "command_run", json!({"id": "select.deselect", "params": {}})),
    ];
    for (name, tool, args) in steps {
        match s.tool(log, tool, args) {
            Ok(r) => log.check(name, !is_error(&r), &text_of(&r)),
            Err(e) => log.check(name, false, &e),
        }
    }
    match s.tool(log, "doc_inspect", json!({})) {
        Ok(r) => {
            let t = text_of(&r);
            log.check("inspect-layers", !is_error(&r) && t.contains("red box"), &t.chars().take(600).collect::<String>());
        }
        Err(e) => log.check("inspect-layers", false, &e),
    }

    // A request written in three fragments, with pauses, still gets one answer.
    let id = s.next_id;
    s.next_id += 1;
    let whole = format!("{}\n", json!({"jsonrpc": "2.0", "id": id, "method": "tools/call", "params": {"name": "session_list", "arguments": {}}}));
    let bytes = whole.as_bytes();
    let (a, b) = (bytes.len() / 3, 2 * bytes.len() / 3);
    let mut written = true;
    for part in [&bytes[..a], &bytes[a..b], &bytes[b..]] {
        written &= s.write_raw(log, part).is_ok();
        std::thread::sleep(Duration::from_millis(300));
    }
    match s.response(log, id) {
        Ok(v) => log.check("fragmented-request", written && v.get("result").is_some(), &text_of(v.get("result").unwrap_or(&Value::Null))),
        Err(e) => log.check("fragmented-request", false, &e),
    }

    // Saves: native PNG and layered PSD in the write root, then reopen the PNG.
    for (name, path) in [("save-png", "mcp-out.png"), ("save-psd", "mcp-out.psd")] {
        match s.tool(log, "doc_save", json!({"path": path})) {
            Ok(r) => log.check(name, !is_error(&r), &text_of(&r)),
            Err(e) => log.check(name, false, &e),
        }
    }
    match s.tool(log, "doc_open", json!({"path": "mcp-out.png"})) {
        Ok(r) => {
            let t = text_of(&r);
            log.check("reopen-png", !is_error(&r) && t.contains("64") && t.contains("48"), &t);
        }
        Err(e) => log.check("reopen-png", false, &e),
    }

    preservation(&mut s, log, workdir);

    // Tool errors: a missing file, an escaping path, an unknown command, an unknown tool.
    for (name, tool, args) in [
        ("error-missing-file", "doc_open", json!({"path": "no-such-file.png"})),
        ("error-escape", "doc_open", json!({"path": "../outside.png"})),
        ("error-unknown-command", "command_run", json!({"id": "no.such.command"})),
    ] {
        match s.tool(log, tool, args) {
            Ok(r) => log.check(name, is_error(&r), &text_of(&r)),
            Err(e) => log.check(name, false, &e),
        }
    }
    match s.call(log, "tools/call", json!({"name": "no_such_tool", "arguments": {}})) {
        Ok(v) => log.check("error-unknown-tool", v.get("error").is_some() || v.get("result").is_some_and(is_error), &v.to_string()),
        Err(e) => log.check("error-unknown-tool", false, &e),
    }

    // A soft link inside the root that leads out of it (the guest script makes `escape-link`
    // with MakeLink SOFT). Reading or writing through it must be refused.
    let link = std::path::Path::new(workdir).join("escape-link");
    match std::fs::symlink_metadata(&link) {
        Ok(m) => {
            log.note(&format!("escape-link present, is_symlink={}", m.file_type().is_symlink()));
            for (name, tool, args) in [
                ("link-read-refused", "doc_open", json!({"path": "escape-link/secret.png"})),
                ("link-write-refused", "doc_save", json!({"path": "escape-link/new.png"})),
            ] {
                match s.tool(log, tool, args) {
                    Ok(r) => log.check(name, is_error(&r), &text_of(&r)),
                    Err(e) => log.check(name, false, &e),
                }
            }
        }
        Err(_) => log.note("no escape-link in the work directory; link refusal not tested"),
    }

    // Two requests in flight before reading either; answers matched by id.
    let first = s.request(log, "tools/list", json!({}));
    let second = s.request(log, "tools/call", json!({"name": "doc_inspect", "arguments": {}}));
    match (first, second) {
        (Ok(a), Ok(b)) => {
            let mut seen = Vec::new();
            let mut problem = None;
            for _ in 0..2 {
                match s.next(log, REPLY_TIMEOUT) {
                    Ok(v) => seen.push(v.get("id").and_then(Value::as_u64)),
                    Err(e) => problem = Some(e),
                }
            }
            seen.sort();
            let mut want = vec![Some(a), Some(b)];
            want.sort();
            log.check("concurrent-requests", problem.is_none() && seen == want, &format!("ids {seen:?} expected {want:?} {}", problem.unwrap_or_default()));
        }
        _ => log.check("concurrent-requests", false, "write failed"),
    }

    // A rendered preview comes back as an image.
    match s.tool(log, "render_preview", json!({"max_side": 64})) {
        Ok(r) => {
            let image = r.get("content").and_then(Value::as_array).and_then(|c| c.iter().find(|x| x.get("type").and_then(Value::as_str) == Some("image")));
            let bytes = image.and_then(|i| i.get("data")).and_then(Value::as_str).map_or(0, str::len);
            log.check("render-preview", !is_error(&r) && bytes > 100, &format!("base64 bytes {bytes}"));
            if let Some(data) = image.and_then(|i| i.get("data")).and_then(Value::as_str) {
                log.note(&format!("preview-png-base64 {data}"));
            }
        }
        Err(e) => log.check("render-preview", false, &e),
    }

    // End of input ends the server.
    match s.finish(log) {
        Ok((code, stderr, elapsed)) => {
            log.check("eof-exit", code == 0, &format!("exit {code} after {:.1}s", elapsed.as_secs_f64()));
            log.note(&format!("server stderr: {stderr}"));
        }
        Err(e) => log.check("eof-exit", false, &e),
    }
}

/// Temporary files a save left in `dir` (the atomic save's `.<name>.<pid>-<n>.pcsave.tmp`).
fn leftovers(dir: &str) -> Vec<String> {
    std::fs::read_dir(dir)
        .map(|d| d.flatten().map(|e| e.file_name().to_string_lossy().into_owned()).filter(|n| n.ends_with(".pcsave.tmp")).collect())
        .unwrap_or_default()
}

/// Replacing a file, a save that must fail on a delete-protected file (the guest script makes
/// `locked.png` and protects it), and a non-ASCII name sent as JSON (UTF-8).
fn preservation(s: &mut Session, log: &mut Log, workdir: &str) {
    let steps: Vec<(&str, &str, Value)> = vec![
        ("overwrite-new", "doc_new", json!({"width": 40, "height": 30})),
        ("overwrite-save", "doc_save", json!({"path": "mcp-out.png"})),
    ];
    for (name, tool, args) in steps {
        match s.tool(log, tool, args) {
            Ok(r) => log.check(name, !is_error(&r), &text_of(&r)),
            Err(e) => log.check(name, false, &e),
        }
    }
    match s.tool(log, "doc_open", json!({"path": "mcp-out.png"})) {
        Ok(r) => {
            let t = text_of(&r);
            log.check("overwrite-reopen", !is_error(&r) && t.contains("40") && t.contains("30"), &t);
        }
        Err(e) => log.check("overwrite-reopen", false, &e),
    }
    let locked = format!("{workdir}/locked.png");
    match std::fs::read(&locked) {
        Ok(before) => {
            match s.tool(log, "doc_save", json!({"path": "locked.png"})) {
                Ok(r) => log.check("save-locked-refused", is_error(&r), &text_of(&r)),
                Err(e) => log.check("save-locked-refused", false, &e),
            }
            let after = std::fs::read(&locked).unwrap_or_default();
            log.check("save-locked-unchanged", after == before, &format!("{} bytes before, {} after", before.len(), after.len()));
        }
        Err(e) => log.note(&format!("no {locked} ({e}); the delete-protected save is not checked")),
    }
    let name = "za\u{17c}\u{f3}\u{142}\u{107} g\u{119}\u{15b}l\u{105}.png";
    match s.tool(log, "doc_save", json!({"path": name})) {
        Ok(r) => log.check("utf8-name-save", !is_error(&r), &text_of(&r)),
        Err(e) => log.check("utf8-name-save", false, &e),
    }
    match s.tool(log, "doc_open", json!({"path": name})) {
        Ok(r) => log.check("utf8-name-reopen", !is_error(&r), &text_of(&r)),
        Err(e) => log.check("utf8-name-reopen", false, &e),
    }
    let names: Vec<String> = std::fs::read_dir(workdir)
        .map(|d| d.flatten().map(|e| e.file_name().as_encoded_bytes().iter().map(|b| if b.is_ascii_graphic() || *b == b' ' { (*b as char).to_string() } else { format!("\\x{b:02x}") }).collect()).collect())
        .unwrap_or_default();
    log.note(&format!("names in the write root, as bytes: {names:?}"));
    let left = leftovers(workdir);
    log.check("no-temporary-files", left.is_empty(), &format!("{left:?}"));
}

fn short_sessions(cli: &str, workdir: &str, log: &mut Log) {
    for round in 1..=3 {
        let name = format!("restart-{round}");
        match Session::start(cli, workdir) {
            Ok(mut s) => {
                let ok = initialize(&mut s, log, &format!("{name}-initialize"));
                if round == 3 && ok {
                    // End of input with a request still unanswered: the server must still end.
                    let _ = s.request(log, "tools/call", json!({"name": "doc_new", "arguments": {"width": 32, "height": 32}}));
                }
                match s.finish(log) {
                    Ok((code, stderr, elapsed)) => log.check(
                        &format!("{name}-exit"),
                        code == 0,
                        &format!("exit {code} after {:.1}s; stderr: {}", elapsed.as_secs_f64(), stderr.trim()),
                    ),
                    Err(e) => log.check(&format!("{name}-exit"), false, &e),
                }
            }
            Err(e) => log.check(&name, false, &e.to_string()),
        }
    }
}

/// A session that ends while the client still holds standard input open: the server must
/// say on stderr that it waits for the client, stay until standard input is closed, and then
/// exit promptly with an error status. `send` writes the input that ends the session.
fn held_stdin_case(cli: &str, workdir: &str, log: &mut Log, name: &str, send: &dyn Fn(&mut Session, &mut Log) -> std::io::Result<()>, wait: Duration) {
    let mut s = match Session::start(cli, workdir) {
        Ok(s) => s,
        Err(e) => return log.check(name, false, &e.to_string()),
    };
    let started = Instant::now();
    if let Err(e) = send(&mut s, log) {
        return log.check(name, false, &format!("write failed: {e}"));
    }
    log.note(&format!("{name}: input written after {:.1}s", started.elapsed().as_secs_f64()));
    // Give the server time to notice; it must not exit while its read is pending.
    let deadline = Instant::now() + wait;
    let mut exited_early = None;
    while Instant::now() < deadline {
        if let Ok(Some(status)) = s.child.try_wait() {
            exited_early = Some(status.code().unwrap_or(-1));
            break;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    let held_for = started.elapsed();
    match s.finish(log) {
        Ok((code, stderr, total)) => {
            let after_close = total.saturating_sub(held_for);
            let waited = stderr.contains("waiting for the client to close standard input");
            log.note(&format!("{name}: stderr: {}", stderr.trim()));
            // The wait-for-the-client contract is the AROS port's; on other hosts (upstream's
            // Tokio stdin) the check is only that the process ends with an error, at the latest
            // promptly after standard input is closed.
            let contract = if cfg!(target_os = "aros") { exited_early.is_none() && waited } else { true };
            log.check(
                name,
                contract && code != 0 && after_close < Duration::from_secs(20),
                &format!(
                    "alive while stdin open: {}; exit {code} {:.1}s after close; wait notice: {waited}",
                    exited_early.is_none(),
                    after_close.as_secs_f64()
                ),
            );
        }
        Err(e) => log.check(name, false, &e),
    }
}

fn held_stdin_cases(cli: &str, workdir: &str, log: &mut Log) {
    // A request before initialize fails the MCP handshake.
    held_stdin_case(
        cli,
        workdir,
        log,
        "held-stdin-failed-init",
        &|s: &mut Session, log: &mut Log| s.request(log, "tools/list", json!({})).map(|_| ()),
        Duration::from_secs(10),
    );
    // A line longer than the 1 MiB limit (no newline; one 64 KiB step past it) ends the session
    // before any of it reaches the protocol layer.
    held_stdin_case(
        cli,
        workdir,
        log,
        "held-stdin-oversized-line",
        &|s: &mut Session, log: &mut Log| {
            let ok = initialize(s, log, "oversized-initialize");
            if !ok {
                return Err(std::io::Error::other("initialize failed"));
            }
            let stdin = s.stdin.as_mut().ok_or_else(|| std::io::Error::other("stdin closed"))?;
            let block = vec![b'x'; 64 * 1024];
            for _ in 0..17 {
                stdin.write_all(&block)?;
            }
            stdin.flush()
        },
        Duration::from_secs(900),
    );
}

fn main() {
    // --quick: the main session and the restarts only, without the held-stdin cases (one of
    // which sends 1.1 MB through a pipe and then waits 15 minutes): a release smoke test.
    let all: Vec<String> = std::env::args().skip(1).collect();
    let quick = all.iter().any(|a| a == "--quick");
    let args: Vec<String> = all.into_iter().filter(|a| a != "--quick").collect();
    if args.len() < 3 {
        eprintln!("usage: photocraft-mcp-check [--quick] CLI WORKDIR REPORT [TRANSCRIPT]");
        std::process::exit(2);
    }
    let report = match std::fs::OpenOptions::new().create_new(true).write(true).open(&args[2]) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("photocraft-mcp-check: cannot create {} ({e}); reports are never overwritten", args[2]);
            std::process::exit(2);
        }
    };
    let transcript = args.get(3).and_then(|p| std::fs::OpenOptions::new().create_new(true).write(true).open(p).ok());
    let mut log = Log { report, transcript, pass: 0, fail: 0 };
    log.note(&format!("cli {} workdir {}", args[0], args[1]));
    main_session(&args[0], &args[1], &mut log);
    short_sessions(&args[0], &args[1], &mut log);
    if quick {
        log.note("quick run: held-stdin cases skipped");
    } else {
        held_stdin_cases(&args[0], &args[1], &mut log);
    }
    let (pass, fail) = (log.pass, log.fail);
    let _ = writeln!(log.report, "SUMMARY pass={pass} fail={fail}");
    let _ = log.report.flush();
    std::process::exit(if fail == 0 && pass > 0 { 0 } else { 1 });
}
