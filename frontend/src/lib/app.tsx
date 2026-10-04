import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { getVersion } from "@tauri-apps/api/app";
import { api, type DeviceCapabilities, type Settings } from "./api";

export type ViewId = "setup" | "models" | "ocr" | "platforms" | "device";

interface AppState {
  view: ViewId;
  navigate: (view: ViewId) => void;
  version: string | null;
  caps: DeviceCapabilities | null;
  refreshCaps: () => Promise<void>;
  settings: Settings | null;
  updateSettings: (patch: { default_model_id?: string; cloud_enabled?: boolean }) => Promise<void>;
  settingsError: string | null;
  // Bumped whenever something app-wide changes (a setting, a finished read), so views
  // that show derived numbers can refetch.
  revision: number;
  bump: () => void;
}

const AppContext = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [view, setView] = useState<ViewId>("setup");
  const [version, setVersion] = useState<string | null>(null);
  const [caps, setCaps] = useState<DeviceCapabilities | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  const refreshCaps = useCallback(async () => {
    try {
      setCaps(await api.deviceCapabilities());
    } catch {
      // Views that need the numbers show their own "couldn't reach" message.
    }
  }, []);

  useEffect(() => {
    if ("__TAURI_INTERNALS__" in window) void getVersion().then(setVersion);
    void refreshCaps();
    api.getSettings().then(setSettings, (err) => setSettingsError(String(err)));
  }, [refreshCaps]);

  const updateSettings = useCallback(
    async (patch: { default_model_id?: string; cloud_enabled?: boolean }) => {
      setSettingsError(null);
      try {
        setSettings(await api.updateSettings(patch));
        setRevision((r) => r + 1);
      } catch (err) {
        setSettingsError(err instanceof Error ? err.message : String(err));
      }
    },
    [],
  );

  const bump = useCallback(() => setRevision((r) => r + 1), []);

  return (
    <AppContext.Provider
      value={{
        view,
        navigate: setView,
        version,
        caps,
        refreshCaps,
        settings,
        updateSettings,
        settingsError,
        revision,
        bump,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}
