// "Open file" and "Show in folder" act on the computer running DocBox's backend. They
// make sense in the desktop app, or in a browser on that same computer; from another
// device (e.g. through a reverse proxy) they would open things the viewer can't see.
export const IN_TAURI = "__TAURI_INTERNALS__" in window;

export const ON_BACKEND_COMPUTER =
  IN_TAURI || ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
