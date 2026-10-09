//! `crewboard serve`: the Unix socket daemon around `Board`.

use std::io;
use std::os::unix::fs::FileTypeExt;
use std::path::Path;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;

use serde_json::{Value, json};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::net::unix::{OwnedReadHalf, OwnedWriteHalf};
use tokio::net::{UnixListener, UnixStream};

use crate::board::{Board, Limits, Subscription};

type Shared = Arc<Mutex<Board>>;

fn lock(board: &Shared) -> MutexGuard<'_, Board> {
    board.lock().expect("board lock poisoned")
}

fn err(e: &str) -> Value {
    json!({"ok": false, "error": e})
}

pub fn run(path: &Path, limits: Limits) -> io::Result<()> {
    if std::os::unix::net::UnixStream::connect(path).is_ok() {
        return Err(io::Error::new(io::ErrorKind::AddrInUse, format!("{} already serves a board", path.display())));
    }
    // A socket nobody answers on is left by a stopped daemon; replace it, but never another file type.
    match std::fs::symlink_metadata(path) {
        Ok(m) if m.file_type().is_socket() => std::fs::remove_file(path)?,
        Ok(_) => return Err(io::Error::new(io::ErrorKind::AlreadyExists, format!("{} is not a socket", path.display()))),
        Err(_) => {}
    }
    tokio::runtime::Builder::new_current_thread().enable_all().build()?.block_on(async {
        // SAFETY: umask and getuid only read or set this process's own attributes.
        // umask 0177 makes bind create the socket as 0600, with no window at a wider mode.
        let old = unsafe { libc::umask(0o177) };
        let listener = UnixListener::bind(path);
        unsafe { libc::umask(old) };
        let listener = listener?;
        let uid = unsafe { libc::getuid() };
        eprintln!("crewboard: serving {}", path.display());
        let board = Arc::new(Mutex::new(Board::new(limits)));
        loop {
            match listener.accept().await {
                Ok((stream, _)) => {
                    tokio::spawn(conn(stream, board.clone(), uid));
                }
                Err(e) => {
                    // Usually out of file descriptors: back off instead of spinning.
                    eprintln!("crewboard: accept: {e}");
                    tokio::time::sleep(Duration::from_millis(100)).await;
                }
            }
        }
    })
}

/// Serves one connection: one JSON request per line until EOF or a `sub`.
async fn conn(stream: UnixStream, board: Shared, uid: u32) -> io::Result<()> {
    let cred = stream.peer_cred()?;
    if cred.uid() != uid {
        return Ok(());
    }
    let pid = cred.pid().unwrap_or(0);
    // JSON escapes can grow a body six-fold (`\u0000`); the rest of a request is small.
    let max_line = lock(&board).limits.max_msg * 6 + 4096;
    let (r, mut w) = stream.into_split();
    let mut r = BufReader::new(r);
    let mut line = Vec::new();
    loop {
        line.clear();
        let n = (&mut r).take(max_line as u64).read_until(b'\n', &mut line).await?;
        if n == 0 {
            return Ok(());
        }
        if n == max_line && line.last() != Some(&b'\n') {
            return w.write_all(format!("{}\n", err("too_large")).as_bytes()).await;
        }
        let req: Value = serde_json::from_slice(&line).unwrap_or(Value::Null);
        let reply = if req["op"] == "sub" {
            match subscribe(&board, &req) {
                Ok(sub) => return stream_sub(r, w, board, sub).await,
                Err(e) => format!("{}\n", err(e)),
            }
        } else {
            answer(&board, pid, &req)
        };
        w.write_all(reply.as_bytes()).await?;
    }
}

fn subscribe(board: &Shared, req: &Value) -> Result<Subscription, &'static str> {
    let topics = req["topics"].as_array().and_then(|a| a.iter().map(|t| t.as_str().map(String::from)).collect());
    lock(board).subscribe(topics.ok_or("bad_request")?, req["since"].as_u64())
}

/// The reply lines to any request but `sub`, newline included.
fn answer(board: &Shared, pid: i32, req: &Value) -> String {
    let mut b = lock(board);
    let reply = match req["op"].as_str() {
        Some("pub") => match (req["topic"].as_str(), req["body"].as_str()) {
            (Some(topic), Some(body)) => match b.publish(topic, req["from"].as_str(), pid, body) {
                Ok(seq) => json!({"ok": true, "seq": seq}),
                Err(e) => err(e),
            },
            _ => err("bad_request"),
        },
        Some("hist") => {
            let lines = b.history(req["topic"].as_str().unwrap_or(""), req["n"].as_u64().unwrap_or(50) as usize);
            return lines.concat() + "{\"end\":true}\n";
        }
        Some("topics") => b.topics(),
        Some("stat") => b.stat(),
        _ => err("bad_request"),
    };
    format!("{reply}\n")
}

/// A stalled write ends the connection after this long.
const WRITE_TIMEOUT: Duration = Duration::from_secs(5);

async fn put(w: &mut OwnedWriteHalf, line: &str) -> io::Result<()> {
    tokio::time::timeout(WRITE_TIMEOUT, w.write_all(line.as_bytes())).await.unwrap_or_else(|_| Err(io::ErrorKind::TimedOut.into()))
}

/// Streams replay then live messages until the client closes its end or falls behind.
async fn stream_sub(mut r: BufReader<OwnedReadHalf>, mut w: OwnedWriteHalf, board: Shared, sub: Subscription) -> io::Result<()> {
    let (id, replay, mut rx) = sub;
    let reader = tokio::spawn(async move {
        let mut sink = [0u8; 256];
        while matches!(r.read(&mut sink).await, Ok(n) if n > 0) {}
    });
    let stop_reader = reader.abort_handle();
    let shared = board.clone();
    let writer = tokio::spawn(async move {
        let _ = async {
            for line in replay {
                put(&mut w, &line).await?;
            }
            while let Some(line) = rx.recv().await {
                put(&mut w, &line).await?;
            }
            // The board drops the sender only when this subscriber's queue is full.
            // Every queued line is written by now, so the notice cannot split a line.
            let _ = w.as_ref().try_write(b"{\"error\":\"slow\"}\n");
            Ok::<(), io::Error>(())
        }
        .await;
        lock(&shared).unsubscribe(id);
        // Dropping both halves closes the socket.
        drop(w);
        stop_reader.abort();
    });
    let _ = reader.await;
    writer.abort();
    lock(&board).unsubscribe(id);
    Ok(())
}
