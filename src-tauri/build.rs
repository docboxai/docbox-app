use std::path::PathBuf;

// tauri-build refuses to build when a declared sidecar (`bundle.externalBin`) is missing.
// Release CI downloads a pinned, checksum-verified `uv` into `binaries/` before building;
// for local builds, fall back to copying the developer's own `uv` from PATH so
// `cargo tauri dev` / `cargo tauri build` just work.
fn ensure_uv_sidecar() {
    let target = std::env::var("TARGET").expect("cargo sets TARGET");
    let ext = if target.contains("windows") { ".exe" } else { "" };
    let dest = PathBuf::from("binaries").join(format!("uv-{target}{ext}"));
    println!("cargo:rerun-if-changed={}", dest.display());
    if dest.exists() {
        return;
    }
    let exe = format!("uv{ext}");
    let found = std::env::var_os("PATH").and_then(|paths| {
        std::env::split_paths(&paths)
            .map(|dir| dir.join(&exe))
            .find(|candidate| candidate.is_file())
    });
    let Some(src) = found else {
        panic!(
            "uv sidecar missing at {} and no `uv` on PATH to copy. Install uv \
             (https://docs.astral.sh/uv/) or place the binary there.",
            dest.display()
        );
    };
    std::fs::create_dir_all("binaries").expect("create binaries/");
    std::fs::copy(&src, &dest).expect("copy uv sidecar");
    println!("cargo:warning=copied local uv from {} as the sidecar", src.display());
}

fn main() {
    // Declaring any rerun-if-changed (as ensure_uv_sidecar does) turns off cargo's
    // default of rerunning on every change, so list the inputs tauri_build embeds too —
    // otherwise an icon-only change keeps the old window/taskbar icon.
    println!("cargo:rerun-if-changed=icons");
    println!("cargo:rerun-if-changed=tauri.conf.json");
    println!("cargo:rerun-if-changed=capabilities");
    ensure_uv_sidecar();
    tauri_build::build()
}
