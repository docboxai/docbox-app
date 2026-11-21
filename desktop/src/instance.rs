//! One running DocBox per data folder. A second launch hands over to the running one, which
//! brings its window to the front, instead of starting a second backend (and first-run
//! `uv sync`) on the same data.
//!
//! The running app holds an exclusive lock on `<data>/instance.lock` for as long as it
//! runs (the OS releases it when the process ends, crashed or not) and listens on a
//! loopback port written to `<data>/instance.port` (a file of its own: on Windows a locked
//! file can't be read by anyone else). A second launch that can't take the lock reads the
//! port, sends a token, and exits.

use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::path::Path;
use std::time::Duration;

const TOKEN: &[u8] = b"docbox:show\n";

pub enum Instance {
    /// This process is the running app. Keep the lock alive until it exits; `shown` gets a
    /// message each time a later launch asks for the window.
    Primary { _lock: File, shown: futures::channel::mpsc::UnboundedReceiver<()> },
    /// Another DocBox runs on this data folder and was asked to show its window.
    Secondary,
}

pub fn claim(data_dir: &Path) -> std::io::Result<Instance> {
    std::fs::create_dir_all(data_dir)?;
    let port_path = data_dir.join("instance.port");
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(data_dir.join("instance.lock"))?;
    match file.try_lock() {
        Ok(()) => {}
        Err(std::fs::TryLockError::WouldBlock) => {
            let text = std::fs::read_to_string(&port_path).unwrap_or_default();
            if let Ok(port) = text.trim().parse::<u16>() {
                let addr = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
                if let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_secs(2)) {
                    let _ = stream.write_all(TOKEN);
                }
            }
            return Ok(Instance::Secondary);
        }
        Err(std::fs::TryLockError::Error(err)) => return Err(err),
    }

    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))?;
    let port = listener.local_addr()?.port();
    std::fs::write(&port_path, port.to_string())?;

    let (tx, rx) = futures::channel::mpsc::unbounded();
    std::thread::spawn(move || {
        for stream in listener.incoming() {
            let Ok(mut stream) = stream else { continue };
            let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
            let mut buf = [0u8; 32];
            let mut read = 0;
            while read < TOKEN.len() {
                match stream.read(&mut buf[read..]) {
                    Ok(0) | Err(_) => break,
                    Ok(n) => read += n,
                }
            }
            // Anything else that finds the port (it's on loopback) is ignored.
            if &buf[..read] == TOKEN && tx.unbounded_send(()).is_err() {
                return;
            }
        }
    });
    Ok(Instance::Primary { _lock: file, shown: rx })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_second_launch_hands_over_to_the_first() {
        let dir = std::env::temp_dir().join(format!("docbox-instance-{}", std::process::id()));
        let first = claim(&dir).unwrap();
        let Instance::Primary { mut shown, _lock } = first else { panic!("first launch") };
        assert!(matches!(claim(&dir).unwrap(), Instance::Secondary));
        let got = futures::executor::block_on(futures::StreamExt::next(&mut shown));
        assert_eq!(got, Some(()));
        drop(_lock);
        // Once the first is gone, the next launch runs.
        assert!(matches!(claim(&dir).unwrap(), Instance::Primary { .. }));
        let _ = std::fs::remove_dir_all(&dir);
    }
}
