//! Two clients talk through a real `crewboard serve` on a socket in a temp dir:
//! pub/sub, history with `--since` and the gap marker, the caps, and a restart.

use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdout, Command, Output, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

use serde_json::Value;

const BIN: &str = env!("CARGO_BIN_EXE_crewboard");

/// Kills the child process when the test ends, pass or fail.
struct Proc(Child);

impl Drop for Proc {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn cmd(sock: &Path, dir: &Path, args: &[&str]) -> Command {
    let mut c = Command::new(BIN);
    // Never the real runtime dir: both variables point into the temp dir.
    c.args(args).env("CREWBOARD_SOCKET", sock).env("XDG_RUNTIME_DIR", dir).env_remove("FM_TASK_ID");
    c
}

fn run(sock: &Path, dir: &Path, args: &[&str]) -> Output {
    cmd(sock, dir, args).output().unwrap()
}

fn stdout(o: &Output) -> String {
    assert!(o.status.success(), "{o:?}");
    String::from_utf8(o.stdout.clone()).unwrap()
}

fn stat(sock: &Path, dir: &Path) -> Value {
    serde_json::from_str(&stdout(&run(sock, dir, &["stat"]))).unwrap()
}

fn serve(sock: &Path, dir: &Path) -> Proc {
    let args = ["serve", "--socket", sock.to_str().unwrap(), "--history", "3", "--cap-bytes", "1500", "--max-msg", "300"];
    let daemon = Proc(cmd(sock, dir, &args).stderr(Stdio::null()).spawn().unwrap());
    let start = Instant::now();
    while !run(sock, dir, &["stat"]).status.success() {
        assert!(start.elapsed() < Duration::from_secs(10), "daemon did not start");
        std::thread::sleep(Duration::from_millis(20));
    }
    daemon
}

/// A subscriber whose stdout lines arrive on a channel, so reads can time out.
fn sub(sock: &Path, dir: &Path, args: &[&str]) -> (Proc, mpsc::Receiver<String>) {
    let mut child = cmd(sock, dir, args).stdout(Stdio::piped()).stderr(Stdio::null()).spawn().unwrap();
    let out: ChildStdout = child.stdout.take().unwrap();
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        for line in BufReader::new(out).lines().map_while(Result::ok) {
            if tx.send(line).is_err() {
                break;
            }
        }
    });
    (Proc(child), rx)
}

fn recv(rx: &mpsc::Receiver<String>) -> Value {
    serde_json::from_str(&rx.recv_timeout(Duration::from_secs(10)).expect("no message")).unwrap()
}

#[test]
fn two_clients_history_caps_and_restart() {
    let dir: PathBuf = std::env::temp_dir().join(format!("crewboard-test-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
    let sock = dir.join("crewboard.sock");
    let (sock, dir) = (sock.as_path(), dir.as_path());

    // No daemon: every client exits 3 with "board off".
    let o = run(sock, dir, &["stat"]);
    assert_eq!(o.status.code(), Some(3));
    assert_eq!(String::from_utf8_lossy(&o.stderr).trim(), "crewboard: board off");

    let mut daemon = serve(sock, dir);
    assert_eq!(std::fs::metadata(sock).unwrap().permissions().mode() & 0o777, 0o600);

    // Client A subscribes; client B publishes as an argument and from stdin.
    let (mut a, a_rx) = sub(sock, dir, &["sub", "task/a", "fleet", "--since", "0", "--json"]);
    let o = cmd(sock, dir, &["pub", "task/a", "hello"]).env("FM_TASK_ID", "b").output().unwrap();
    assert_eq!(stdout(&o).trim(), "1");
    let mut b = cmd(sock, dir, &["pub", "fleet"]).stdin(Stdio::piped()).stdout(Stdio::piped()).spawn().unwrap();
    b.stdin.take().unwrap().write_all(b"from stdin\n").unwrap();
    assert_eq!(stdout(&b.wait_with_output().unwrap()).trim(), "2");
    let m = recv(&a_rx);
    assert_eq!((&m["seq"], &m["topic"], &m["from"], &m["body"]), (&1.into(), &"task/a".into(), &"b".into(), &"hello".into()));
    assert!(m["pid"].as_u64().unwrap() > 0);
    assert_eq!(recv(&a_rx)["body"], "from stdin");

    // History keeps 3 per topic: seq 1 and 3 leave task/a.
    for body in ["3", "4", "5"] {
        stdout(&run(sock, dir, &["pub", "task/a", body]));
    }
    for want in [3, 4, 5] {
        assert_eq!(recv(&a_rx)["seq"], want);
    }
    assert_eq!(stdout(&run(sock, dir, &["tail", "task/a", "-n", "2"])).lines().map(|l| &l[..1]).collect::<Vec<_>>(), ["4", "5"]);
    let (_late, late_rx) = sub(sock, dir, &["sub", "task/a", "--since", "0", "--json"]);
    assert_eq!(recv(&late_rx), serde_json::json!({"gap": true, "oldest": 3}));
    for want in [3, 4, 5] {
        assert_eq!(recv(&late_rx)["seq"], want);
    }
    let (_caught_up, rx) = sub(sock, dir, &["sub", "task/*", "--since", "3", "--json"]);
    assert_eq!(recv(&rx)["seq"], 4);

    // Message size limit, then the global cap evicts the oldest messages first.
    let o = run(sock, dir, &["pub", "fleet", &"x".repeat(301)]);
    assert_eq!((o.status.code(), String::from_utf8_lossy(&o.stderr).trim()), (Some(1), "crewboard: too_large"));
    for i in 0..10 {
        stdout(&run(sock, dir, &["pub", &format!("bulk/{i}"), &"x".repeat(250)]));
    }
    let s = stat(sock, dir);
    assert!(s["bytes"].as_u64().unwrap() <= 1500, "{s}");
    assert_eq!(stdout(&run(sock, dir, &["tail", "task/a"])), "");
    assert_eq!(stdout(&run(sock, dir, &["tail", "bulk/9"])).lines().count(), 1);

    // Restart: subscribers see the board go off; the new daemon starts empty with a new boot id.
    let boot = s["boot"].clone();
    daemon.0.kill().unwrap();
    daemon.0.wait().unwrap();
    assert_eq!(a.0.wait().unwrap().code(), Some(3));
    assert_eq!(run(sock, dir, &["stat"]).status.code(), Some(3));
    let restarted = serve(sock, dir);
    let s = stat(sock, dir);
    assert_ne!(s["boot"], boot);
    assert_eq!((&s["seq"], &s["topics"], &s["bytes"]), (&0.into(), &0.into(), &0.into()));
    assert_eq!(stdout(&run(sock, dir, &["pub", "task/a", "after restart"])).trim(), "1");

    drop(restarted);
    std::fs::remove_dir_all(dir).unwrap();
}

/// A subscriber that never reads is dropped and its connection closed, not kept with its queue.
#[test]
fn stalled_subscriber_is_closed() {
    use std::io::Read;
    use std::os::unix::net::UnixStream;

    let dir: PathBuf = std::env::temp_dir().join(format!("crewboard-stall-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
    let sock = dir.join("crewboard.sock");
    let (sock, dir) = (sock.as_path(), dir.as_path());
    let args = ["serve", "--socket", sock.to_str().unwrap(), "--cap-bytes", "8000000"];
    let _daemon = Proc(cmd(sock, dir, &args).stderr(Stdio::null()).spawn().unwrap());
    let start = Instant::now();
    while !run(sock, dir, &["stat"]).status.success() {
        assert!(start.elapsed() < Duration::from_secs(10), "daemon did not start");
        std::thread::sleep(Duration::from_millis(20));
    }

    let mut stalled = UnixStream::connect(sock).unwrap();
    stalled.write_all(b"{\"op\":\"sub\",\"topics\":[\"*\"]}\n").unwrap();
    while stat(sock, dir)["subs"] != 1 {
        std::thread::sleep(Duration::from_millis(20));
    }

    // Big lines fill the socket buffer, stall the writer, then fill the queue past 1024.
    let mut publisher = UnixStream::connect(sock).unwrap();
    let mut replies = BufReader::new(publisher.try_clone().unwrap());
    let body = "x".repeat(60_000);
    for _ in 0..1100 {
        writeln!(publisher, "{{\"op\":\"pub\",\"topic\":\"t\",\"body\":\"{body}\"}}").unwrap();
        let mut reply = String::new();
        replies.read_line(&mut reply).unwrap();
        assert!(reply.contains("\"ok\":true"), "{reply}");
    }
    let s = stat(sock, dir);
    assert_eq!((&s["subs"], &s["dropped"]), (&0.into(), &1.into()));

    // Once the write times out the daemon closes the socket, which frees the queued lines.
    stalled.set_read_timeout(Some(Duration::from_secs(20))).unwrap();
    let mut buf = vec![0u8; 1 << 16];
    loop {
        match stalled.read(&mut buf) {
            Ok(0) => break,
            Ok(_) => {}
            Err(e) if e.kind() == std::io::ErrorKind::ConnectionReset => break,
            Err(e) => panic!("connection still open: {e}"),
        }
    }
    std::fs::remove_dir_all(dir).unwrap();
}
