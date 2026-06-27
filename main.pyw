from __future__ import annotations

import ctypes
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import customtkinter as ctk
    from customtkinter import filedialog as ctk_filedialog
except ImportError:
    print("[FATAL] customtkinter not installed. Run: pip install customtkinter")
    sys.exit(1)

try:
    from PIL import Image, ImageTk
except ImportError:
    print("[FATAL] Pillow not installed. Run: pip install Pillow")
    sys.exit(1)

try:
    import pygame
    import pygame.mixer
except ImportError:
    print("[FATAL] pygame not installed. Run: pip install pygame")
    sys.exit(1)

try:
    import win32api
    import win32con
    import win32gui
except ImportError:
    print("[FATAL] pywin32 not installed. Run: pip install pywin32")
    sys.exit(1)

logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("FocusShell")

CONFIG_FILE: str = "focus_shell_config.json"
ASSETS_MUSIC_DIR: str = os.path.join("assets", "music")
ASSETS_WALLPAPER_DIR: str = os.path.join("assets", "wallpapers")
AUDIO_FORMATS: tuple[str, ...] = (".mp3", ".wav", ".ogg", ".flac")
DEFAULT_WALLPAPER_COLOR: str = "#0d1117"
FADE_STEP_MS: int = 35  
SETTINGS_PANEL_WIDTH: int = 420
APP_TITLE: str = "FocusShell"

DEFAULT_CONFIG: dict[str, Any] = {
    "theme": "dark",
    "wallpaper": "",
    "volume": 0.6,
    "shortcuts": [
        {"label": "Notepad", "path": "notepad.exe", "icon": ""},
        {"label": "Terminal", "path": "cmd.exe", "icon": ""},
        {"label": "Explorer", "path": "explorer.exe", "icon": ""},
        {"label": "Calculator", "path": "calc.exe", "icon": ""},
        {"label": "Paint", "path": "mspaint.exe", "icon": ""},
        {"label": "WordPad", "path": "write.exe", "icon": ""},
    ],
}


class ConfigManager:

    def __init__(self, config_path: str = CONFIG_FILE) -> None:
        self.config_path: str = config_path
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        try:
            if not os.path.exists(self.config_path):
                log.info("Config file not found — initialising defaults.")
                self._data = DEFAULT_CONFIG.copy()
                self.save()
                return

            with open(self.config_path, "r", encoding="utf-8") as fh:
                loaded: dict[str, Any] = json.load(fh)

            merged: dict[str, Any] = DEFAULT_CONFIG.copy()
            merged.update(loaded)
            self._data = merged
            log.info("Config loaded from '%s'.", self.config_path)

        except json.JSONDecodeError as exc:
            log.error("Config JSON is malformed (%s). Resetting to defaults.", exc)
            self._data = DEFAULT_CONFIG.copy()
            self.save()
        except Exception as exc:
            log.error("Unexpected error loading config: %s", exc)
            self._data = DEFAULT_CONFIG.copy()

    def save(self) -> None:
        try:
            tmp_path: str = f"{self.config_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=4, ensure_ascii=False)
            os.replace(tmp_path, self.config_path)
            log.debug("Config saved to '%s'.", self.config_path)
        except Exception as exc:
            log.error("Failed to save config: %s", exc)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    def get_shortcuts(self) -> list[dict[str, str]]:
        shortcuts = self._data.get("shortcuts", [])
        return shortcuts if isinstance(shortcuts, list) else []

    def add_shortcut(self, label: str, path: str, icon: str = "") -> bool:
        try:
            resolved: Optional[str] = path if os.path.isabs(path) else shutil.which(path)
            if resolved is None:
                resolved = path  

            if not os.path.exists(resolved) and shutil.which(path) is None:
                log.warning("Shortcut path does not exist on host filesystem: %s", path)
                return False

            shortcuts: list[dict[str, str]] = self.get_shortcuts()
            shortcuts.append({"label": label, "path": path, "icon": icon})
            self._data["shortcuts"] = shortcuts
            self.save()
            log.info("Shortcut added: label='%s' path='%s'", label, path)
            return True
        except Exception as exc:
            log.error("Error adding shortcut: %s", exc)
            return False

    def remove_shortcut(self, index: int) -> None:
        try:
            shortcuts: list[dict[str, str]] = self.get_shortcuts()
            if 0 <= index < len(shortcuts):
                removed = shortcuts.pop(index)
                self._data["shortcuts"] = shortcuts
                self.save()
                log.info("Shortcut removed: %s", removed)
        except Exception as exc:
            log.error("Error removing shortcut: %s", exc)

    def get_volume(self) -> float:
        return float(self._data.get("volume", 0.6))

    def set_volume(self, vol: float) -> None:
        self._data["volume"] = max(0.0, min(1.0, vol))
        self.save()

    def get_wallpaper(self) -> str:
        return str(self._data.get("wallpaper", ""))

    def set_wallpaper(self, path: str) -> None:
        self._data["wallpaper"] = path
        self.save()

    def get_theme(self) -> str:
        return str(self._data.get("theme", "dark"))

    def set_theme(self, theme: str) -> None:
        self._data["theme"] = theme
        self.save()


class WindowsSystemWrapper:

    TASKBAR_CLASS: str = "Shell_TrayWnd"

    def __init__(self) -> None:
        self._taskbar_hwnd: Optional[int] = None
        self._original_window_style: dict[int, int] = {}
        self._locate_taskbar()

    def _locate_taskbar(self) -> None:
        try:
            hwnd: int = win32gui.FindWindow(self.TASKBAR_CLASS, None)
            if hwnd:
                self._taskbar_hwnd = hwnd
                log.debug("Taskbar handle found: 0x%X", hwnd)
            else:
                log.warning("Taskbar window handle not found.")
        except Exception as exc:
            log.error("Error locating taskbar: %s", exc)

    def hide_taskbar(self) -> None:
        try:
            if not self._taskbar_hwnd:
                self._locate_taskbar()
            if self._taskbar_hwnd:
                win32gui.ShowWindow(self._taskbar_hwnd, win32con.SW_HIDE)
                log.info("Taskbar hidden.")
        except Exception as exc:
            log.error("Failed to hide taskbar: %s", exc)

    def show_taskbar(self) -> None:
        try:
            if self._taskbar_hwnd:
                win32gui.ShowWindow(self._taskbar_hwnd, win32con.SW_SHOW)
                win32gui.UpdateWindow(self._taskbar_hwnd)
                log.info("Taskbar restored.")
            else:
                log.warning("Cannot restore taskbar — handle not found.")
        except Exception as exc:
            log.error("Failed to show taskbar: %s", exc)

    def make_borderless_fullscreen(self, window_title: str) -> None:
        try:
            hwnd: int = win32gui.FindWindow(None, window_title)
            if not hwnd:
                log.warning("Window with title '%s' not found.", window_title)
                return

            screen_w: int = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            screen_h: int = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

            original_style: int = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            self._original_window_style[hwnd] = original_style

            borderless_style: int = original_style & ~(
                win32con.WS_OVERLAPPEDWINDOW
                | win32con.WS_CAPTION
                | win32con.WS_THICKFRAME
                | win32con.WS_MINIMIZEBOX
                | win32con.WS_MAXIMIZEBOX
                | win32con.WS_SYSMENU
            )
            win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, borderless_style)

            ex_style: int = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(
                hwnd,
                win32con.GWL_EXSTYLE,
                ex_style & ~win32con.WS_EX_DLGMODALFRAME,
            )

            flags = (
                win32con.SWP_NOZORDER
                | win32con.SWP_NOACTIVATE
                | win32con.SWP_FRAMECHANGED
            )
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, 0, 0, screen_w, screen_h, flags)
            log.info("Window '%s' set to borderless fullscreen (%dx%d).", window_title, screen_w, screen_h)

        except Exception as exc:
            log.error("Failed to make window borderless fullscreen: %s", exc)

    def restore_window_style(self, window_title: str) -> None:
        try:
            hwnd: int = win32gui.FindWindow(None, window_title)
            if hwnd and hwnd in self._original_window_style:
                win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, self._original_window_style[hwnd])
                win32gui.SetWindowPos(
                    hwnd,
                    None,
                    100,
                    100,
                    1280,
                    720,
                    win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED,
                )
                del self._original_window_style[hwnd]
                log.info("Window style restored for '%s'.", window_title)
        except Exception as exc:
            log.error("Error restoring window style: %s", exc)

    @staticmethod
    def get_screen_resolution() -> tuple[int, int]:
        try:
            w: int = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            h: int = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            return w, h
        except Exception as exc:
            log.error("Failed to read screen resolution: %s", exc)
            return 1920, 1080

    @staticmethod
    def set_dpi_awareness() -> None:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  
        except AttributeError:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception as exc:
                log.warning("DPI awareness could not be set: %s", exc)
        except Exception as exc:
            log.warning("DPI awareness could not be set (shcore): %s", exc)


class AmbientAudioEngine:

    def __init__(self, music_dir: str = ASSETS_MUSIC_DIR) -> None:
        self.music_dir: str = music_dir
        self._tracks: list[str] = []
        self._current_index: int = 0
        self._is_playing: bool = False
        self._current_volume: float = 0.6
        self._fade_thread: Optional[threading.Thread] = None
        self._fade_lock: threading.Lock = threading.Lock()
        self._initialized: bool = False

        self._ensure_music_dir()
        self._init_mixer()
        self._scan_tracks()

    def _ensure_music_dir(self) -> None:
        try:
            os.makedirs(self.music_dir, exist_ok=True)
        except Exception as exc:
            log.error("Cannot create music directory '%s': %s", self.music_dir, exc)

    def _init_mixer(self) -> None:
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            self._initialized = True
            log.info("Pygame mixer initialised (44100 Hz, 16-bit stereo).")
        except pygame.error as exc:
            log.error("Pygame mixer init failed: %s", exc)
        except Exception as exc:
            log.error("Unexpected error during mixer init: %s", exc)

    def _scan_tracks(self) -> None:
        try:
            if not os.path.isdir(self.music_dir):
                log.warning("Music directory '%s' does not exist.", self.music_dir)
                self._tracks = []
                return

            found: list[str] = []
            for fname in sorted(os.listdir(self.music_dir)):
                if any(fname.lower().endswith(ext) for ext in AUDIO_FORMATS):
                    found.append(os.path.join(self.music_dir, fname))

            self._tracks = found
            if found:
                log.info("Found %d audio track(s) in '%s'.", len(found), self.music_dir)
            else:
                log.info("No audio tracks found in '%s'. Ambient audio disabled.", self.music_dir)
        except Exception as exc:
            log.error("Error scanning music directory: %s", exc)
            self._tracks = []

    def rescan(self) -> None:
        self._scan_tracks()

    def play(self) -> None:
        if not self._initialized:
            log.warning("Mixer not initialised — cannot play.")
            return
        if not self._tracks:
            log.info("No tracks available to play.")
            return

        try:
            if pygame.mixer.music.get_busy() and not self._is_playing:
                pygame.mixer.music.unpause()
                self._is_playing = True
                log.info("Playback resumed.")
                return

            track: str = self._tracks[self._current_index]
            pygame.mixer.music.load(track)
            pygame.mixer.music.set_volume(self._current_volume)
            pygame.mixer.music.play()
            self._is_playing = True
            log.info("Now playing: %s", os.path.basename(track))
        except pygame.error as exc:
            log.error("Pygame playback error: %s", exc)
        except Exception as exc:
            log.error("Unexpected playback error: %s", exc)

    def pause(self) -> None:
        if not self._initialized:
            return
        try:
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.pause()
                self._is_playing = False
                log.info("Playback paused.")
        except Exception as exc:
            log.error("Error pausing music: %s", exc)

    def stop(self) -> None:
        if not self._initialized:
            return
        try:
            pygame.mixer.music.stop()
            self._is_playing = False
            log.info("Playback stopped.")
        except Exception as exc:
            log.error("Error stopping music: %s", exc)

    def skip_next(self) -> None:
        if not self._tracks:
            return
        try:
            self._current_index = (self._current_index + 1) % len(self._tracks)
            self.stop()
            self.play()
            log.info("Skipped to next track [%d/%d].", self._current_index + 1, len(self._tracks))
        except Exception as exc:
            log.error("Error skipping to next track: %s", exc)

    def skip_prev(self) -> None:
        if not self._tracks:
            return
        try:
            self._current_index = (self._current_index - 1) % len(self._tracks)
            self.stop()
            self.play()
            log.info("Skipped to previous track [%d/%d].", self._current_index + 1, len(self._tracks))
        except Exception as exc:
            log.error("Error skipping to previous track: %s", exc)

    def set_volume_immediate(self, volume: float) -> None:
        if not self._initialized:
            return
        try:
            clamped: float = max(0.0, min(1.0, volume))
            self._current_volume = clamped
            pygame.mixer.music.set_volume(clamped)
        except Exception as exc:
            log.error("Error setting immediate volume: %s", exc)

    def fade_to_volume(self, target_volume: float, duration_ms: int = 1500) -> None:
        target: float = max(0.0, min(1.0, target_volume))

        def _fade_worker() -> None:
            with self._fade_lock:
                start_vol: float = self._current_volume
                steps: int = max(1, duration_ms // FADE_STEP_MS)
                delta: float = (target - start_vol) / steps

                for step in range(steps):
                    new_vol: float = max(0.0, min(1.0, start_vol + delta * (step + 1)))
                    try:
                        if self._initialized:
                            pygame.mixer.music.set_volume(new_vol)
                        self._current_volume = new_vol
                    except Exception as exc:
                        log.error("Fade step error: %s", exc)
                        break
                    time.sleep(FADE_STEP_MS / 1000.0)

                self._current_volume = target
                try:
                    if self._initialized:
                        pygame.mixer.music.set_volume(target)
                except Exception as exc:
                    log.error("Final fade clamp error: %s", exc)

        try:
            self._fade_thread = threading.Thread(
                target=_fade_worker, name="AudioFadeThread", daemon=True
            )
            self._fade_thread.start()
            log.debug("Fade thread started: %.2f → %.2f over %dms.", self._current_volume, target, duration_ms)
        except Exception as exc:
            log.error("Failed to start fade thread: %s", exc)

    def crossfade_next(self, fade_out_ms: int = 1200, fade_in_ms: int = 1200) -> None:
        def _crossfade_worker() -> None:
            try:
                self.fade_to_volume(0.0, duration_ms=fade_out_ms)
                if self._fade_thread and self._fade_thread.is_alive():
                    self._fade_thread.join(timeout=(fade_out_ms / 1000.0) + 0.5)
                self._current_index = (self._current_index + 1) % max(1, len(self._tracks))
                self.stop()
                self.play()
                self.fade_to_volume(0.6, duration_ms=fade_in_ms)
            except Exception as exc:
                log.error("Crossfade error: %s", exc)

        try:
            threading.Thread(target=_crossfade_worker, name="CrossfadeThread", daemon=True).start()
        except Exception as exc:
            log.error("Failed to start crossfade thread: %s", exc)

    def get_current_track_name(self) -> str:
        if not self._tracks:
            return ""
        try:
            return os.path.basename(self._tracks[self._current_index])
        except Exception:
            return ""

    def get_track_count(self) -> int:
        return len(self._tracks)

    def get_current_index(self) -> int:
        return self._current_index

    def is_playing(self) -> bool:
        return self._is_playing

    def get_volume(self) -> float:
        return self._current_volume

    def teardown(self) -> None:
        try:
            self.stop()
            if self._initialized:
                pygame.mixer.quit()
            log.info("Audio engine shut down.")
        except Exception as exc:
            log.error("Error during audio teardown: %s", exc)


class SettingsPanel(ctk.CTkFrame):

    def __init__(
        self,
        master: ctk.CTk,
        config: ConfigManager,
        audio: AmbientAudioEngine,
        refresh_callback: Callable[[], None],
        **kwargs: Any,
    ) -> None:
        super().__init__(
            master,
            width=SETTINGS_PANEL_WIDTH,
            corner_radius=0,
            fg_color="#111827",
            border_width=1,
            border_color="#1f2937",
            **kwargs,
        )
        self.config: ConfigManager = config
        self.audio: AmbientAudioEngine = audio
        self.refresh_callback: Callable[[], None] = refresh_callback
        self._visible: bool = False
        self._build_ui()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(
            self,
            text="⚙  Settings",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color="#f9fafb",
            anchor="w",
        )
        header.grid(row=0, column=0, padx=24, pady=(28, 8), sticky="ew")

        divider_top = ctk.CTkFrame(self, height=1, fg_color="#1f2937")
        divider_top.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="ew")

        audio_label = ctk.CTkLabel(
            self,
            text="AMBIENT AUDIO",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#6b7280",
            anchor="w",
        )
        audio_label.grid(row=2, column=0, padx=24, pady=(0, 4), sticky="ew")

        self._track_label = ctk.CTkLabel(
            self,
            text=self._get_track_display(),
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color="#9ca3af",
            anchor="w",
            wraplength=360,
        )
        self._track_label.grid(row=3, column=0, padx=24, pady=(0, 8), sticky="ew")

        controls_frame = ctk.CTkFrame(self, fg_color="transparent")
        controls_frame.grid(row=4, column=0, padx=24, pady=(0, 12), sticky="ew")
        controls_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        btn_cfg = {
            "width": 44,
            "height": 36,
            "corner_radius": 8,
            "fg_color": "#1f2937",
            "hover_color": "#374151",
            "font": ctk.CTkFont(size=16)
        }
        ctk.CTkButton(controls_frame, text="⏮", command=self._prev_track, **btn_cfg).grid(row=0, column=0, padx=2)
        ctk.CTkButton(controls_frame, text="▶", command=self._play, **btn_cfg).grid(row=0, column=1, padx=2)
        ctk.CTkButton(controls_frame, text="⏸", command=self._pause, **btn_cfg).grid(row=0, column=2, padx=2)
        ctk.CTkButton(controls_frame, text="⏹", command=self._stop, **btn_cfg).grid(row=0, column=3, padx=2)
        ctk.CTkButton(controls_frame, text="⏭", command=self._next_track, **btn_cfg).grid(row=0, column=4, padx=2)

        vol_row = ctk.CTkFrame(self, fg_color="transparent")
        vol_row.grid(row=5, column=0, padx=24, pady=(0, 4), sticky="ew")
        vol_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(vol_row, text="🔊", font=ctk.CTkFont(size=15), text_color="#9ca3af").grid(row=0, column=0, padx=(0, 8))

        self._vol_slider = ctk.CTkSlider(
            vol_row,
            from_=0.0,
            to=1.0,
            number_of_steps=100,
            command=self._on_volume_change,
            button_color="#3b82f6",
            progress_color="#3b82f6",
            height=18,
        )
        self._vol_slider.set(self.config.get_volume())
        self._vol_slider.grid(row=0, column=1, sticky="ew")

        self._vol_pct_label = ctk.CTkLabel(
            vol_row,
            text=f"{int(self.config.get_volume() * 100)}%",
            font=ctk.CTkFont(size=12),
            text_color="#6b7280",
            width=40,
        )
        self._vol_pct_label.grid(row=0, column=2, padx=(8, 0))

        divider_1 = ctk.CTkFrame(self, height=1, fg_color="#1f2937")
        divider_1.grid(row=6, column=0, padx=16, pady=16, sticky="ew")

        wp_label = ctk.CTkLabel(
            self,
            text="WALLPAPER",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#6b7280",
            anchor="w",
        )
        wp_label.grid(row=7, column=0, padx=24, pady=(0, 6), sticky="ew")

        self._wallpaper_path_label = ctk.CTkLabel(
            self,
            text=self._truncate_path(self.config.get_wallpaper() or "No wallpaper set"),
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color="#9ca3af",
            anchor="w",
            wraplength=360,
        )
        self._wallpaper_path_label.grid(row=8, column=0, padx=24, pady=(0, 8), sticky="ew")

        ctk.CTkButton(
            self,
            text="Browse Wallpaper…",
            command=self._pick_wallpaper,
            corner_radius=8,
            fg_color="#1f2937",
            hover_color="#374151",
            border_width=1,
            border_color="#374151",
            font=ctk.CTkFont(size=13),
            height=36,
        ).grid(row=9, column=0, padx=24, pady=(0, 4), sticky="ew")

        ctk.CTkButton(
            self,
            text="Remove Wallpaper",
            command=self._remove_wallpaper,
            corner_radius=8,
            fg_color="transparent",
            hover_color="#1f2937",
            border_width=1,
            border_color="#374151",
            text_color="#ef4444",
            font=ctk.CTkFont(size=12),
            height=32,
        ).grid(row=10, column=0, padx=24, pady=(0, 4), sticky="ew")

        divider_2 = ctk.CTkFrame(self, height=1, fg_color="#1f2937")
        divider_2.grid(row=11, column=0, padx=16, pady=16, sticky="ew")

        sc_label = ctk.CTkLabel(
            self,
            text="ADD SHORTCUT",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#6b7280",
            anchor="w",
        )
        sc_label.grid(row=12, column=0, padx=24, pady=(0, 8), sticky="ew")

        self._sc_label_entry = ctk.CTkEntry(
            self,
            placeholder_text="Label (e.g. VS Code)",
            height=36,
            corner_radius=8,
            border_color="#374151",
            fg_color="#1f2937",
            font=ctk.CTkFont(size=13),
        )
        self._sc_label_entry.grid(row=13, column=0, padx=24, pady=(0, 6), sticky="ew")

        self._sc_path_entry = ctk.CTkEntry(
            self,
            placeholder_text="Absolute path or executable name",
            height=36,
            corner_radius=8,
            border_color="#374151",
            fg_color="#1f2937",
            font=ctk.CTkFont(size=13),
        )
        self._sc_path_entry.grid(row=14, column=0, padx=24, pady=(0, 6), sticky="ew")

        browse_path_btn = ctk.CTkButton(
            self,
            text="Browse Executable…",
            command=self._browse_executable,
            corner_radius=8,
            fg_color="#1f2937",
            hover_color="#374151",
            border_width=1,
            border_color="#374151",
            font=ctk.CTkFont(size=12),
            height=32,
        )
        browse_path_btn.grid(row=15, column=0, padx=24, pady=(0, 8), sticky="ew")

        self._sc_status_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12), text_color="#10b981", anchor="w")
        self._sc_status_label.grid(row=16, column=0, padx=24, pady=(0, 4), sticky="ew")

        ctk.CTkButton(
            self,
            text="+ Add Shortcut",
            command=self._inject_shortcut,
            corner_radius=8,
            fg_color="#3b82f6",
            hover_color="#2563eb",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
        ).grid(row=17, column=0, padx=24, pady=(0, 16), sticky="ew")

        divider_3 = ctk.CTkFrame(self, height=1, fg_color="#1f2937")
        divider_3.grid(row=18, column=0, padx=16, pady=(0, 16), sticky="ew")

        ctk.CTkButton(
            self,
            text="Close Panel",
            command=self.hide,
            corner_radius=8,
            fg_color="transparent",
            hover_color="#1f2937",
            border_width=1,
            border_color="#374151",
            font=ctk.CTkFont(size=13),
            text_color="#9ca3af",
            height=36,
        ).grid(row=19, column=0, padx=24, pady=(0, 24), sticky="ew")

    def _on_volume_change(self, value: float) -> None:
        try:
            self.audio.fade_to_volume(float(value), duration_ms=200)
            self.config.set_volume(float(value))
            self._vol_pct_label.configure(text=f"{int(float(value) * 100)}%")
        except Exception as exc:
            log.error("Settings volume change error: %s", exc)

    def _play(self) -> None:
        self.audio.play()
        self._update_track_label()

    def _pause(self) -> None:
        self.audio.pause()

    def _stop(self) -> None:
        self.audio.stop()

    def _next_track(self) -> None:
        self.audio.skip_next()
        self._update_track_label()

    def _prev_track(self) -> None:
        self.audio.skip_prev()
        self._update_track_label()

    def _update_track_label(self) -> None:
        try:
            self._track_label.configure(text=self._get_track_display())
        except Exception as exc:
            log.error("Error updating track label: %s", exc)

    def _get_track_display(self) -> str:
        name = self.audio.get_current_track_name()
        count = self.audio.get_track_count()
        if not name:
            return "No tracks loaded"
        return f"♪  [{self.audio.get_current_index() + 1}/{count}]  {name}"

    def _pick_wallpaper(self) -> None:
        try:
            os.makedirs(ASSETS_WALLPAPER_DIR, exist_ok=True)
            path: str = ctk_filedialog.askopenfilename(
                title="Select Wallpaper Image",
                filetypes=[
                    ("Image Files", "*.png *.jpg *.jpeg *.bmp *.webp *.tiff"),
                    ("All Files", "*.*"),
                ],
            )
            if not path or not os.path.exists(path):
                return

            dest_path: str = os.path.join(ASSETS_WALLPAPER_DIR, os.path.basename(path))
            shutil.copy2(path, dest_path)
            self.config.set_wallpaper(dest_path)
            self._wallpaper_path_label.configure(text=self._truncate_path(dest_path))
            log.info("Wallpaper set to '%s'.", dest_path)
            self.refresh_callback()
        except Exception as exc:
            log.error("Wallpaper picker error: %s", exc)

    def _remove_wallpaper(self) -> None:
        try:
            self.config.set_wallpaper("")
            self._wallpaper_path_label.configure(text="No wallpaper set")
            self.refresh_callback()
            log.info("Wallpaper removed.")
        except Exception as exc:
            log.error("Error removing wallpaper: %s", exc)

    def _browse_executable(self) -> None:
        try:
            path: str = ctk_filedialog.askopenfilename(
                title="Select Executable",
                filetypes=[
                    ("Executables", "*.exe *.bat *.cmd *.ps1 *.sh"),
                    ("All Files", "*.*"),
                ],
            )
            if path:
                self._sc_path_entry.delete(0, "end")
                self._sc_path_entry.insert(0, path)
        except Exception as exc:
            log.error("Browse executable error: %s", exc)

    def _inject_shortcut(self) -> None:
        try:
            label: str = self._sc_label_entry.get().strip()
            path: str = self._sc_path_entry.get().strip()

            if not label:
                self._set_sc_status("Label cannot be empty.", error=True)
                return
            if not path:
                self._set_sc_status("Path cannot be empty.", error=True)
                return

            resolved = path if os.path.isabs(path) and os.path.exists(path) else shutil.which(path)

            if resolved is None:
                self._set_sc_status(f"Path not found: {path}", error=True)
                log.warning("Shortcut rejected — path not found on filesystem: %s", path)
                return

            if self.config.add_shortcut(label=label, path=path):
                self._set_sc_status(f"'{label}' added successfully.", error=False)
                self._sc_label_entry.delete(0, "end")
                self._sc_path_entry.delete(0, "end")
                self.refresh_callback()
            else:
                self._set_sc_status("Failed to add shortcut. Check logs.", error=True)
        except Exception as exc:
            log.error("Shortcut injection error: %s", exc)
            self._set_sc_status(f"Error: {exc}", error=True)

    def _set_sc_status(self, msg: str, error: bool = False) -> None:
        try:
            self._sc_status_label.configure(text=msg, text_color="#ef4444" if error else "#10b981")
        except Exception as exc:
            log.error("Error setting status label: %s", exc)

    def show(self) -> None:
        try:
            self.place(relx=1.0, rely=0.0, anchor="ne", relheight=1.0, width=SETTINGS_PANEL_WIDTH)
            self._visible = True
            self._update_track_label()
            self.lift()
        except Exception as exc:
            log.error("Error showing settings panel: %s", exc)

    def hide(self) -> None:
        try:
            self.place_forget()
            self._visible = False
        except Exception as exc:
            log.error("Error hiding settings panel: %s", exc)

    def toggle(self) -> None:
        self.hide() if self._visible else self.show()

    def is_visible(self) -> bool:
        return self._visible

    @staticmethod
    def _truncate_path(path: str, max_len: int = 46) -> str:
        return path if len(path) <= max_len else f"…{path[-(max_len - 1):]}"


class FocusShellUI(ctk.CTk):

    def __init__(self, config: ConfigManager, system: WindowsSystemWrapper) -> None:
        super().__init__()
        self.config: ConfigManager = config
        self.system: WindowsSystemWrapper = system

        self.audio: AmbientAudioEngine = AmbientAudioEngine()
        self._settings_panel: Optional[SettingsPanel] = None

        self._wallpaper_photo: Optional[ImageTk.PhotoImage] = None
        self._canvas: Optional[ctk.CTkCanvas] = None
        self._tiles_frame: Optional[ctk.CTkFrame] = None

        self._configure_window()
        self._build_ui()
        self._apply_wallpaper()
        self._render_shortcuts()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        try:
            self.audio.set_volume_immediate(self.config.get_volume())
        except Exception as exc:
            log.error("Error setting initial volume: %s", exc)

        if self.audio.get_track_count() > 0:
            self.audio.play()

    def _configure_window(self) -> None:
        try:
            ctk.set_appearance_mode(self.config.get_theme())
            ctk.set_default_color_theme("blue")

            self.title(APP_TITLE)
            screen_w, screen_h = self.system.get_screen_resolution()
            self.geometry(f"{screen_w}x{screen_h}+0+0")

            self.attributes("-fullscreen", True)
            self.attributes("-topmost", True)
            self.overrideredirect(True)
            self.focus_force()
            log.info("Window configured: %dx%d fullscreen.", screen_w, screen_h)
        except Exception as exc:
            log.error("Window configuration error: %s", exc)

    def _build_ui(self) -> None:
        try:
            self.grid_rowconfigure(0, weight=0)  
            self.grid_rowconfigure(1, weight=1)  
            self.grid_columnconfigure(0, weight=1)

            self._topbar = ctk.CTkFrame(self, height=56, fg_color="#0d1117e0", corner_radius=0)
            self._topbar.grid(row=0, column=0, sticky="ew")
            self._topbar.grid_columnconfigure(1, weight=1)
            self._topbar.grid_propagate(False)

            ctk.CTkLabel(
                self._topbar,
                text="  ◈  FocusShell",
                font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
                text_color="#f9fafb",
            ).grid(row=0, column=0, padx=(16, 0), sticky="w")

            self._clock_label = ctk.CTkLabel(self._topbar, text="", font=ctk.CTkFont(family="Segoe UI", size=15), text_color="#9ca3af")
            self._clock_label.grid(row=0, column=1, padx=16, sticky="e")
            self._tick_clock()

            self._settings_btn = ctk.CTkButton(
                self._topbar,
                text="⚙",
                width=44,
                height=36,
                corner_radius=8,
                fg_color="#1f2937",
                hover_color="#374151",
                font=ctk.CTkFont(size=18),
                command=self._toggle_settings,
            )
            self._settings_btn.grid(row=0, column=2, padx=(0, 12))

            self._scroll_frame = ctk.CTkScrollableFrame(
                self,
                fg_color="transparent",
                scrollbar_button_color="#1f2937",
                scrollbar_button_hover_color="#374151",
            )
            self._scroll_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
            self._scroll_frame.grid_columnconfigure(tuple(range(6)), weight=1)

            self._settings_panel = SettingsPanel(
                master=self,
                config=self.config,
                audio=self.audio,
                refresh_callback=self._full_refresh,
            )

            log.info("UI layout constructed.")
        except Exception as exc:
            log.error("UI build error: %s", exc)

    def _apply_wallpaper(self) -> None:
        try:
            wp_path: str = self.config.get_wallpaper()
            screen_w, screen_h = self.system.get_screen_resolution()

            if wp_path and os.path.exists(wp_path):
                img: Image.Image = Image.open(wp_path).convert("RGBA").resize((screen_w, screen_h), Image.LANCZOS)
                self._wallpaper_photo = ImageTk.PhotoImage(img)
                self.configure(bg="black")

                if self._canvas:
                    self._canvas.destroy()

                self._canvas = ctk.CTkCanvas(self, width=screen_w, height=screen_h, highlightthickness=0, bd=0)
                self._canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0)
                self._canvas.create_image(0, 0, anchor="nw", image=self._wallpaper_photo)
                self._canvas.lower()  
                log.info("Wallpaper applied: %s", wp_path)
            else:
                self.configure(fg_color=DEFAULT_WALLPAPER_COLOR)
                if self._canvas:
                    self._canvas.destroy()
                    self._canvas = None
                log.info("No wallpaper — using default background colour.")
        except Exception as exc:
            log.error("Wallpaper apply error: %s", exc)

    def _render_shortcuts(self) -> None:
        try:
            for widget in self._scroll_frame.winfo_children():
                widget.destroy()

            shortcuts: list[dict[str, str]] = self.config.get_shortcuts()

            if not shortcuts:
                empty_lbl = ctk.CTkLabel(
                    self._scroll_frame,
                    text="No shortcuts configured.\nOpen ⚙ Settings to add one.",
                    font=ctk.CTkFont(family="Segoe UI", size=18),
                    text_color="#4b5563",
                )
                empty_lbl.grid(row=0, column=0, columnspan=6, pady=120)
                return

            COLS: int = 5
            for idx, shortcut in enumerate(shortcuts):
                self._create_tile(shortcut, idx // COLS, idx % COLS, idx)

            log.info("Rendered %d shortcut tile(s).", len(shortcuts))
        except Exception as exc:
            log.error("Error rendering shortcuts: %s", exc)

    def _create_tile(self, shortcut: dict[str, str], row: int, col: int, idx: int) -> None:
        try:
            label: str = shortcut.get("label", "App")
            path: str = shortcut.get("path", "")
            icon: str = self._guess_icon(path, shortcut.get("icon", ""))

            tile = ctk.CTkButton(
                self._scroll_frame,
                text=f"{icon}\n{label}",
                font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                width=160,
                height=120,
                corner_radius=16,
                fg_color="#111827",
                hover_color="#1f2937",
                border_width=1,
                border_color="#1f2937",
                text_color="#f9fafb",
                compound="top",
                command=lambda p=path: self._launch_app(p),
            )
            tile.grid(row=row, column=col, padx=16, pady=16, sticky="nsew")
            tile.bind("<Button-3>", lambda e, i=idx: self._show_tile_context_menu(e, i))
        except Exception as exc:
            log.error("Error creating tile for '%s': %s", shortcut.get("label", "?"), exc)

    @staticmethod
    def _guess_icon(path: str, explicit_icon: str) -> str:
        if explicit_icon:
            return explicit_icon
        p: str = path.lower()
        mapping = {
            "notepad": "📝", "cmd": "💻", "terminal": "💻", "powershell": "💻",
            "explorer": "📁", "calc": "🔢", "chrome": "🌐", "firefox": "🌐",
            "edge": "🌐", "brave": "🌐", "code": "✏️", "vscode": "✏️",
            "paint": "🎨", "write": "📄", "word": "📄", "vlc": "🎬",
            "media": "🎬", "music": "🎵", "spotify": "🎵"
        }
        for key, emoji in mapping.items():
            if key in p:
                return emoji
        return "⚡"

    def _launch_app(self, path: str) -> None:
        try:
            flags: int = 0x08000000 | 0x00000008
            resolved = path if os.path.isabs(path) and os.path.exists(path) else shutil.which(path)
            if resolved is None:
                resolved = path  

            proc = subprocess.Popen([resolved], creationflags=flags, close_fds=True, shell=False)
            log.info("Launched '%s' (PID %d).", path, proc.pid)
        except FileNotFoundError:
            log.error("Executable not found: %s", path)
            self._show_error_toast(f"Not found: {path}")
        except PermissionError:
            log.error("Permission denied launching: %s", path)
            self._show_error_toast(f"Permission denied: {path}")
        except Exception as exc:
            log.error("Error launching '%s': %s", path, exc)
            self._show_error_toast(f"Launch error: {exc}")

    def _show_tile_context_menu(self, event: Any, shortcut_index: int) -> None:
        try:
            import tkinter as tk
            menu = tk.Menu(
                self, tearoff=0, bg="#111827", fg="#f9fafb",
                activebackground="#1f2937", activeforeground="#f9fafb",
                bd=0, relief="flat"
            )
            menu.add_command(
                label=f"Remove shortcut #{shortcut_index + 1}",
                command=lambda: self._remove_shortcut(shortcut_index),
            )
            menu.tk_popup(event.x_root, event.y_root)
        except Exception as exc:
            log.error("Context menu error: %s", exc)

    def _remove_shortcut(self, index: int) -> None:
        try:
            self.config.remove_shortcut(index)
            self._render_shortcuts()
        except Exception as exc:
            log.error("Error removing shortcut at index %d: %s", index, exc)

    def _show_error_toast(self, message: str, duration_ms: int = 3500) -> None:
        try:
            toast = ctk.CTkLabel(
                self,
                text=f"⚠  {message}",
                font=ctk.CTkFont(family="Segoe UI", size=13),
                fg_color="#7f1d1d",
                text_color="#fca5a5",
                corner_radius=8,
                padx=14,
                pady=10,
            )
            toast.place(relx=0.02, rely=0.94, anchor="sw")
            self.after(duration_ms, toast.destroy)
        except Exception as exc:
            log.error("Toast display error: %s", exc)

    def _tick_clock(self) -> None:
        try:
            import datetime
            self._clock_label.configure(text=datetime.datetime.now().strftime("%A, %d %b %Y  %H:%M:%S"))
        except Exception as exc:
            log.error("Clock tick error: %s", exc)
        finally:
            self.after(1000, self._tick_clock)

    def _toggle_settings(self) -> None:
        try:
            if self._settings_panel:
                self._settings_panel.toggle()
        except Exception as exc:
            log.error("Settings toggle error: %s", exc)

    def _full_refresh(self) -> None:
        try:
            self._apply_wallpaper()
            self._render_shortcuts()
        except Exception as exc:
            log.error("Full refresh error: %s", exc)

    def _on_close(self) -> None:
        log.info("FocusShell closing — restoring system environment.")
        try:
            self.audio.teardown()
        except Exception as exc:
            log.error("Audio teardown error during close: %s", exc)
        try:
            self.system.show_taskbar()
        except Exception as exc:
            log.error("Taskbar restore error during close: %s", exc)
        try:
            self.destroy()
        except Exception as exc:
            log.error("Window destroy error: %s", exc)

    def run(self) -> None:
        try:
            self.mainloop()
        except KeyboardInterrupt:
            log.info("Keyboard interrupt received.")
            self._on_close()
        except Exception as exc:
            log.critical("Unhandled exception in main loop: %s", exc, exc_info=True)
            self._on_close()


def main() -> None:
    system = WindowsSystemWrapper()
    system.set_dpi_awareness()

    config = ConfigManager()

    log.info("Starting FocusShell (%s)", APP_TITLE)

    try:
        os.makedirs(ASSETS_MUSIC_DIR, exist_ok=True)
        os.makedirs(ASSETS_WALLPAPER_DIR, exist_ok=True)
    except Exception as exc:
        log.error("Could not create asset directories: %s", exc)

    app: Optional[FocusShellUI] = None

    try:
        system.hide_taskbar()
        app = FocusShellUI(config=config, system=system)
        app.update_idletasks()
        system.make_borderless_fullscreen(APP_TITLE)

        log.info("FocusShell UI ready. Entering main loop.")
        app.run()

    except Exception as exc:
        log.critical("Fatal error during startup: %s", exc, exc_info=True)
    finally:
        try:
            system.show_taskbar()
            log.info("Taskbar restored in finally block.")
        except Exception as exc:
            log.error("Could not restore taskbar in finally block: %s", exc)


if __name__ == "__main__":
    main()
