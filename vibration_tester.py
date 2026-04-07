import math
import os
import random
import re
import json
import shutil
import subprocess
import time
import tkinter as tk
from tkinter import colorchooser

import customtkinter as ctk
import pygame
from PIL import Image

pygame.init()
pygame.joystick.init()

COLORS = {
    "bg": "#1e1e20",
    "surface": "#26262a",
    "surface_alt": "#303036",
    "border": "#3f3f46",
    "text": "#f6f5f4",
    "muted": "#b8b8bf",
    "accent": "#62a0ea",
    "accent_alt": "#3584e4",
    "ok": "#57e389",
    "warn": "#f6d32d",
    "danger": "#ff7b7b",
    "canvas_bg": "#111318",
    "canvas_grid": "#1e242d",
    "bar": "#7eb6ff",
}

MODE_INFO = {
    "Continuous": "Constant rumble",
    "Pulse": "Interval pulses",
    "Wave": "Smooth wave modulation",
    "Alternating": "Left-right alternation",
}

PRESET_ACCENTS = {
    "Adwaita Blue": "#62a0ea",
    "Mint": "#57e389",
    "Amber": "#f6d32d",
    "Rose": "#ff7b7b",
    "Lavender": "#b48ead",
}

HEX_RE = re.compile(r"^#?[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")


def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def lerp_color(c1, c2, t):
    t = clamp(t, 0.0, 1.0)
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def normalize_hex(value):
    if not value:
        return None
    raw = value.strip()
    if not HEX_RE.match(raw):
        return None
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    return f"#{raw.lower()}"


def scale_color(hex_color, factor):
    r = int(clamp(int(hex_color[1:3], 16) * factor, 0, 255))
    g = int(clamp(int(hex_color[3:5], 16) * factor, 0, 255))
    b = int(clamp(int(hex_color[5:7], 16) * factor, 0, 255))
    return f"#{r:02x}{g:02x}{b:02x}"


class GamepadVibrationTester(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title("Gamepad Haptics")
        self.geometry("900x650")
        self.minsize(760, 560)
        self.configure(fg_color=COLORS["bg"])

        self.joystick = None
        self.joysticks_map = {}

        self.active_mode = None
        self.mode_last_tick = 0.0
        self.mode_phase = 0.0
        self.mode_toggle = False

        self.current_left = 0.0
        self.current_right = 0.0
        self.last_decay = time.time()

        self.bar_count = 42
        self.bar_values = [0.0] * self.bar_count
        self.visual_phase = 0.0
        self.ui_anim_phase = 0.0

        self.icon_svg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons", "svg")
        self.icon_png_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons", "png")
        self.theme_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "theme_colors.json")
        self.icons = self.load_icons(size=16)
        self.settings_window = None
        self.settings_hex_entry = None
        self.settings_preview = None
        self.settings_preset_menu = None
        self.settings_apply_btn = None
        self.settings_pick_btn = None
        self.settings_custom_btn = None

        self.load_theme_from_disk()

        self.setup_ui()
        self.refresh_theme_widgets()
        self.manual_refresh()
        self.control_loop()
        self.visualizer_loop()
        self.ui_animation_loop()

        self.bind("<space>", self.on_space)
        self.bind("<Escape>", self.on_stop_shortcut)
        self.bind("<r>", self.on_refresh_shortcut)

    def load_icons(self, size=16):
        icons = {}
        icon_files = {
            "play": "play.svg",
            "stop": "stop.svg",
            "refresh": "refresh.svg",
            "flash": "flash.svg",
            "settings": "settings.svg",
        }

        if not shutil.which("rsvg-convert"):
            return icons

        os.makedirs(self.icon_png_dir, exist_ok=True)

        for key, filename in icon_files.items():
            svg_path = os.path.join(self.icon_svg_dir, filename)
            png_path = os.path.join(self.icon_png_dir, f"{key}_{size}.png")

            if not os.path.exists(svg_path):
                continue

            try:
                svg_mtime = os.path.getmtime(svg_path)
                png_mtime = os.path.getmtime(png_path) if os.path.exists(png_path) else -1
                if svg_mtime > png_mtime:
                    subprocess.run(
                        [
                            "rsvg-convert",
                            "-w",
                            str(size),
                            "-h",
                            str(size),
                            "-o",
                            png_path,
                            svg_path,
                        ],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )

                image = Image.open(png_path)
                icons[key] = ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))
            except Exception:
                continue

        return icons

    def setup_ui(self):
        root = ctk.CTkFrame(self, fg_color="transparent")
        root.pack(fill="both", expand=True, padx=16, pady=16)

        self.panel = ctk.CTkFrame(
            root,
            fg_color=COLORS["surface"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=12,
        )
        self.panel.pack(fill="x", pady=(0, 10))

        device_row = ctk.CTkFrame(self.panel, fg_color="transparent")
        device_row.pack(fill="x", padx=12, pady=(10, 6))

        ctk.CTkLabel(device_row, text="Device", font=("Cantarell", 12, "bold"), text_color=COLORS["text"]).pack(
            side="left", padx=(0, 8)
        )

        self.device_var = ctk.StringVar(value="No Device")
        self.option_device = ctk.CTkOptionMenu(
            device_row,
            variable=self.device_var,
            values=["No Device"],
            command=self.on_device_select,
            width=420,
            fg_color=COLORS["surface_alt"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_alt"],
            dropdown_fg_color=COLORS["surface"],
            dropdown_hover_color=COLORS["surface_alt"],
            text_color=COLORS["text"],
            font=("Cantarell", 12),
        )
        self.option_device.pack(side="left")

        self.btn_refresh = ctk.CTkButton(
            device_row,
            text="Refresh",
            command=self.manual_refresh,
            width=110,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_alt"],
            text_color="#ffffff",
            font=("Cantarell", 12, "bold"),
            image=self.icons.get("refresh"),
            compound="left",
        )
        self.btn_refresh.pack(side="right")

        self.btn_settings = ctk.CTkButton(
            device_row,
            text="Settings",
            command=self.open_settings,
            width=120,
            fg_color=COLORS["surface_alt"],
            hover_color=COLORS["border"],
            text_color=COLORS["text"],
            font=("Cantarell", 12, "bold"),
            image=self.icons.get("settings"),
            compound="left",
        )
        self.btn_settings.pack(side="right", padx=(0, 8))

        mode_row = ctk.CTkFrame(self.panel, fg_color="transparent")
        mode_row.pack(fill="x", padx=12, pady=6)

        ctk.CTkLabel(mode_row, text="Mode", font=("Cantarell", 12, "bold"), text_color=COLORS["text"]).pack(
            side="left", padx=(0, 8)
        )

        self.mode_var = ctk.StringVar(value="Continuous")
        self.option_mode = ctk.CTkOptionMenu(
            mode_row,
            variable=self.mode_var,
            values=list(MODE_INFO.keys()),
            command=self.on_mode_change,
            width=180,
            fg_color=COLORS["surface_alt"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_alt"],
            dropdown_fg_color=COLORS["surface"],
            dropdown_hover_color=COLORS["surface_alt"],
            text_color=COLORS["text"],
            font=("Cantarell", 12),
        )
        self.option_mode.pack(side="left")

        self.label_mode_desc = ctk.CTkLabel(
            mode_row,
            text=MODE_INFO[self.mode_var.get()],
            font=("Cantarell", 12),
            text_color=COLORS["muted"],
        )
        self.label_mode_desc.pack(side="left", padx=12)

        slider_row = ctk.CTkFrame(self.panel, fg_color="transparent")
        slider_row.pack(fill="x", padx=12, pady=(6, 8))
        slider_row.grid_columnconfigure((0, 1, 2), weight=1)

        left_col = ctk.CTkFrame(slider_row, fg_color="transparent")
        left_col.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.label_left = ctk.CTkLabel(left_col, text="Left 70%", font=("Cantarell", 12), text_color=COLORS["text"])
        self.label_left.pack(anchor="w")
        self.slider_left = ctk.CTkSlider(
            left_col,
            from_=0,
            to=100,
            command=self.update_left,
            progress_color=COLORS["accent"],
            button_color=COLORS["accent_alt"],
            button_hover_color=COLORS["accent_alt"],
            fg_color=COLORS["surface_alt"],
        )
        self.slider_left.set(70)
        self.slider_left.pack(fill="x", pady=(2, 0))

        right_col = ctk.CTkFrame(slider_row, fg_color="transparent")
        right_col.grid(row=0, column=1, sticky="ew", padx=6)

        self.label_right = ctk.CTkLabel(right_col, text="Right 70%", font=("Cantarell", 12), text_color=COLORS["text"])
        self.label_right.pack(anchor="w")
        self.slider_right = ctk.CTkSlider(
            right_col,
            from_=0,
            to=100,
            command=self.update_right,
            progress_color=COLORS["accent"],
            button_color=COLORS["accent_alt"],
            button_hover_color=COLORS["accent_alt"],
            fg_color=COLORS["surface_alt"],
        )
        self.slider_right.set(70)
        self.slider_right.pack(fill="x", pady=(2, 0))

        speed_col = ctk.CTkFrame(slider_row, fg_color="transparent")
        speed_col.grid(row=0, column=2, sticky="ew", padx=(6, 0))

        self.label_speed = ctk.CTkLabel(speed_col, text="Speed 5", font=("Cantarell", 12), text_color=COLORS["text"])
        self.label_speed.pack(anchor="w")
        self.slider_speed = ctk.CTkSlider(
            speed_col,
            from_=1,
            to=10,
            command=self.update_speed,
            progress_color=COLORS["accent"],
            button_color=COLORS["accent_alt"],
            button_hover_color=COLORS["accent_alt"],
            fg_color=COLORS["surface_alt"],
        )
        self.slider_speed.set(5)
        self.slider_speed.pack(fill="x", pady=(2, 0))

        button_row = ctk.CTkFrame(self.panel, fg_color="transparent")
        button_row.pack(fill="x", padx=12, pady=(0, 12))
        button_row.grid_columnconfigure((0, 1, 2), weight=1)

        self.btn_start = ctk.CTkButton(
            button_row,
            text="Start",
            command=self.start_mode,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_alt"],
            text_color="#ffffff",
            font=("Cantarell", 12, "bold"),
            height=36,
            image=self.icons.get("play"),
            compound="left",
        )
        self.btn_start.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.btn_oneshot = ctk.CTkButton(
            button_row,
            text="1s Test",
            command=self.one_shot,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_alt"],
            text_color="#ffffff",
            font=("Cantarell", 12, "bold"),
            height=36,
            image=self.icons.get("flash"),
            compound="left",
        )
        self.btn_oneshot.grid(row=0, column=1, sticky="ew", padx=4)

        self.btn_stop = ctk.CTkButton(
            button_row,
            text="Stop",
            command=self.stop_mode,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_alt"],
            text_color="#ffffff",
            font=("Cantarell", 12, "bold"),
            height=36,
            image=self.icons.get("stop"),
            compound="left",
        )
        self.btn_stop.grid(row=0, column=2, sticky="ew", padx=(4, 0))

        self.visual_card = ctk.CTkFrame(
            root,
            fg_color=COLORS["surface"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=12,
        )
        self.visual_card.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(
            self.visual_card,
            bg=COLORS["canvas_bg"],
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        self.canvas.pack(fill="both", expand=True, padx=10, pady=10)

        self.status_bar = ctk.CTkFrame(
            root,
            fg_color=COLORS["surface"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=10,
            height=40,
        )
        self.status_bar.pack(fill="x", pady=(10, 0))
        self.status_bar.pack_propagate(False)

        self.label_status = ctk.CTkLabel(
            self.status_bar,
            text="Ready",
            font=("Cantarell", 12, "bold"),
            text_color=COLORS["muted"],
        )
        self.label_status.pack(side="left", padx=10)

        self.label_state = ctk.CTkLabel(
            self.status_bar,
            text="Idle",
            font=("Cantarell", 12),
            text_color=COLORS["muted"],
        )
        self.label_state.pack(side="right", padx=10)

    def set_status(self, text, tone="muted"):
        tone_map = {
            "muted": COLORS["muted"],
            "ok": COLORS["ok"],
            "warn": COLORS["warn"],
            "bad": COLORS["danger"],
            "info": COLORS["accent"],
        }
        self.label_status.configure(text=text, text_color=tone_map.get(tone, COLORS["muted"]))

    def load_theme_from_disk(self):
        if not os.path.exists(self.theme_path):
            return
        try:
            with open(self.theme_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            saved = data.get("colors", data)
            if not isinstance(saved, dict):
                return
            for key, value in saved.items():
                if key in COLORS:
                    color = normalize_hex(str(value))
                    if color:
                        COLORS[key] = color
        except Exception:
            return

    def save_theme_to_disk(self):
        payload = {"colors": {k: v for k, v in COLORS.items()}}
        try:
            with open(self.theme_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=True, indent=2)
        except Exception:
            pass

    def refresh_theme_widgets(self):
        self.configure(fg_color=COLORS["bg"])
        self.panel.configure(fg_color=COLORS["surface"], border_color=COLORS["border"])
        self.visual_card.configure(fg_color=COLORS["surface"], border_color=COLORS["border"])
        self.status_bar.configure(fg_color=COLORS["surface"], border_color=COLORS["border"])
        self.canvas.configure(bg=COLORS["canvas_bg"])

        self.option_device.configure(
            fg_color=COLORS["surface_alt"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_alt"],
            dropdown_fg_color=COLORS["surface"],
            dropdown_hover_color=COLORS["surface_alt"],
            text_color=COLORS["text"],
        )
        self.option_mode.configure(
            fg_color=COLORS["surface_alt"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_alt"],
            dropdown_fg_color=COLORS["surface"],
            dropdown_hover_color=COLORS["surface_alt"],
            text_color=COLORS["text"],
        )

        self.slider_left.configure(
            progress_color=COLORS["accent"],
            button_color=COLORS["accent_alt"],
            button_hover_color=COLORS["accent_alt"],
            fg_color=COLORS["surface_alt"],
        )
        self.slider_right.configure(
            progress_color=COLORS["accent"],
            button_color=COLORS["accent_alt"],
            button_hover_color=COLORS["accent_alt"],
            fg_color=COLORS["surface_alt"],
        )
        self.slider_speed.configure(
            progress_color=COLORS["accent"],
            button_color=COLORS["accent_alt"],
            button_hover_color=COLORS["accent_alt"],
            fg_color=COLORS["surface_alt"],
        )

        self.btn_settings.configure(fg_color=COLORS["surface_alt"], hover_color=COLORS["border"], text_color=COLORS["text"])
        self.btn_refresh.configure(fg_color=COLORS["accent"], hover_color=COLORS["accent_alt"])
        self.btn_start.configure(fg_color=COLORS["accent"], hover_color=COLORS["accent_alt"])
        self.btn_oneshot.configure(fg_color=COLORS["accent"], hover_color=COLORS["accent_alt"])
        self.btn_stop.configure(fg_color=COLORS["accent"], hover_color=COLORS["accent_alt"])

        if self.active_mode:
            self.label_state.configure(text_color=COLORS["accent"])
        else:
            self.label_state.configure(text_color=COLORS["muted"])

        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.configure(fg_color=COLORS["surface"])
        if self.settings_preview and self.settings_preview.winfo_exists():
            self.settings_preview.configure(fg_color=COLORS["accent"], border_color=COLORS["border"])
        if self.settings_preset_menu and self.settings_preset_menu.winfo_exists():
            self.settings_preset_menu.configure(
                fg_color=COLORS["surface_alt"],
                button_color=COLORS["accent"],
                button_hover_color=COLORS["accent_alt"],
                dropdown_fg_color=COLORS["surface"],
                dropdown_hover_color=COLORS["surface_alt"],
                text_color=COLORS["text"],
            )
        if self.settings_apply_btn and self.settings_apply_btn.winfo_exists():
            self.settings_apply_btn.configure(fg_color=COLORS["accent"], hover_color=COLORS["accent_alt"])
        if self.settings_pick_btn and self.settings_pick_btn.winfo_exists():
            self.settings_pick_btn.configure(fg_color=COLORS["surface_alt"], hover_color=COLORS["border"], text_color=COLORS["text"])
        if self.settings_custom_btn and self.settings_custom_btn.winfo_exists():
            self.settings_custom_btn.configure(fg_color=COLORS["accent"], hover_color=COLORS["accent_alt"])

    def open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.focus()
            return

        self.settings_window = ctk.CTkToplevel(self)
        self.settings_window.title("Settings")
        self.settings_window.geometry("340x260")
        self.settings_window.resizable(False, False)
        self.settings_window.configure(fg_color=COLORS["surface"])
        self.settings_window.protocol("WM_DELETE_WINDOW", self.close_settings)

        container = ctk.CTkFrame(self.settings_window, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(
            container,
            text="Accent Color",
            font=("Cantarell", 14, "bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w", pady=(0, 6))

        self.settings_preset_var = ctk.StringVar(value="Adwaita Blue")
        preset_row = ctk.CTkFrame(container, fg_color="transparent")
        preset_row.pack(fill="x")

        self.settings_preset_menu = ctk.CTkOptionMenu(
            preset_row,
            variable=self.settings_preset_var,
            values=list(PRESET_ACCENTS.keys()),
            width=190,
            fg_color=COLORS["surface_alt"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_alt"],
            dropdown_fg_color=COLORS["surface"],
            dropdown_hover_color=COLORS["surface_alt"],
            text_color=COLORS["text"],
            font=("Cantarell", 12),
        )
        self.settings_preset_menu.pack(side="left")

        self.settings_apply_btn = ctk.CTkButton(
            preset_row,
            text="Apply",
            width=100,
            command=self.apply_preset_color,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_alt"],
            text_color="#ffffff",
            font=("Cantarell", 12, "bold"),
        )
        self.settings_apply_btn.pack(side="right")

        self.settings_pick_btn = ctk.CTkButton(
            container,
            text="Pick Color",
            command=self.pick_custom_color,
            fg_color=COLORS["surface_alt"],
            hover_color=COLORS["border"],
            text_color=COLORS["text"],
            font=("Cantarell", 12, "bold"),
        )
        self.settings_pick_btn.pack(fill="x", pady=(10, 8))

        entry_row = ctk.CTkFrame(container, fg_color="transparent")
        entry_row.pack(fill="x")

        self.settings_hex_entry = ctk.CTkEntry(
            entry_row,
            placeholder_text="#62a0ea",
            font=("Cantarell", 12),
            text_color=COLORS["text"],
            fg_color=COLORS["surface_alt"],
            border_color=COLORS["border"],
        )
        self.settings_hex_entry.insert(0, COLORS["accent"])
        self.settings_hex_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.settings_custom_btn = ctk.CTkButton(
            entry_row,
            text="Custom",
            width=100,
            command=self.apply_custom_color,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_alt"],
            text_color="#ffffff",
            font=("Cantarell", 12, "bold"),
        )
        self.settings_custom_btn.pack(side="right")

        ctk.CTkLabel(
            container,
            text="Preview",
            font=("Cantarell", 12),
            text_color=COLORS["muted"],
        ).pack(anchor="w", pady=(12, 4))

        self.settings_preview = ctk.CTkFrame(
            container,
            fg_color=COLORS["accent"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8,
            height=34,
        )
        self.settings_preview.pack(fill="x")

    def close_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        self.settings_window = None
        self.settings_hex_entry = None
        self.settings_preview = None
        self.settings_preset_menu = None
        self.settings_apply_btn = None
        self.settings_pick_btn = None
        self.settings_custom_btn = None

    def apply_preset_color(self):
        name = self.settings_preset_var.get() if hasattr(self, "settings_preset_var") else None
        color_value = PRESET_ACCENTS.get(name)
        if color_value:
            self.apply_theme_color(color_value)

    def pick_custom_color(self):
        picked = colorchooser.askcolor(color=COLORS["accent"], parent=self.settings_window)
        if picked and picked[1]:
            self.apply_theme_color(picked[1])
            if self.settings_hex_entry and self.settings_hex_entry.winfo_exists():
                self.settings_hex_entry.delete(0, "end")
                self.settings_hex_entry.insert(0, COLORS["accent"])

    def apply_custom_color(self):
        if not self.settings_hex_entry:
            return
        self.apply_theme_color(self.settings_hex_entry.get())

    def apply_theme_color(self, value):
        accent = normalize_hex(value)
        if not accent:
            self.set_status("Invalid color. Use #RRGGBB or #RGB", tone="warn")
            return

        COLORS["accent"] = accent
        COLORS["accent_alt"] = scale_color(accent, 0.70)
        COLORS["bar"] = scale_color(accent, 1.20)

        self.refresh_theme_widgets()

        if self.settings_preview and self.settings_preview.winfo_exists():
            self.settings_preview.configure(fg_color=COLORS["accent"])
        if self.settings_hex_entry and self.settings_hex_entry.winfo_exists():
            self.settings_hex_entry.delete(0, "end")
            self.settings_hex_entry.insert(0, COLORS["accent"])

        self.save_theme_to_disk()
        self.set_status(f"Theme color: {accent}", tone="info")

    def on_mode_change(self, _choice):
        self.label_mode_desc.configure(text=MODE_INFO[self.mode_var.get()])

    def update_left(self, value):
        self.label_left.configure(text=f"Left {int(value)}%")

    def update_right(self, value):
        self.label_right.configure(text=f"Right {int(value)}%")

    def update_speed(self, value):
        self.label_speed.configure(text=f"Speed {int(value)}")

    def get_levels(self):
        return self.slider_left.get() / 100.0, self.slider_right.get() / 100.0

    def get_speed(self):
        return self.slider_speed.get()

    def manual_refresh(self):
        pygame.event.pump()
        pygame.joystick.quit()
        pygame.joystick.init()

        self.joystick = None
        self.joysticks_map = {}
        names = []

        count = pygame.joystick.get_count()
        if count == 0:
            self.option_device.configure(values=["No Device"])
            self.device_var.set("No Device")
            self.set_status("No device found", tone="bad")
            return

        for i in range(count):
            try:
                j = pygame.joystick.Joystick(i)
                j.init()
                name = f"{i}: {j.get_name()}"
                names.append(name)
                self.joysticks_map[name] = j
            except Exception:
                continue

        self.option_device.configure(values=names)
        if names:
            self.device_var.set(names[0])
            self.on_device_select(names[0])
            self.set_status(f"{len(names)} device found", tone="ok")

    def on_device_select(self, choice):
        if choice in self.joysticks_map:
            self.joystick = self.joysticks_map[choice]
            self.set_status(f"Selected: {choice}", tone="info")
        else:
            self.joystick = None

    def send_rumble(self, left, right, duration_ms):
        if not self.joystick:
            return

        left = clamp(left, 0.0, 1.0)
        right = clamp(right, 0.0, 1.0)
        duration_ms = int(clamp(duration_ms, 1, 1500))

        self.joystick.rumble(left, right, duration_ms)
        self.current_left = left
        self.current_right = right

    def safe_stop_rumble(self):
        if not self.joystick:
            return
        try:
            self.joystick.stop_rumble()
        except Exception:
            pass

    def start_mode(self):
        if not self.joystick:
            self.set_status("Select a device first", tone="warn")
            return

        self.active_mode = self.mode_var.get()
        self.mode_last_tick = time.time()
        self.mode_phase = 0.0
        self.mode_toggle = False

        self.btn_start.configure(text="Running")
        self.label_state.configure(text=f"Mode: {self.active_mode}", text_color=COLORS["accent"])
        self.set_status(f"{self.active_mode} started", tone="info")

    def stop_mode(self):
        if self.active_mode:
            self.set_status("Stopped", tone="muted")

        self.active_mode = None
        self.mode_toggle = False
        self.current_left = 0.0
        self.current_right = 0.0
        self.safe_stop_rumble()

        self.btn_start.configure(text="Start")
        self.label_state.configure(text="Idle", text_color=COLORS["muted"])

    def one_shot(self):
        if not self.joystick:
            self.set_status("Select a device first", tone="warn")
            return

        left, right = self.get_levels()
        try:
            self.send_rumble(left, right, 1000)
            self.set_status("One-shot test sent", tone="info")
        except Exception as exc:
            self.set_status(f"Rumble error: {exc}", tone="bad")

    def run_mode_tick(self, now):
        left_base, right_base = self.get_levels()
        speed = self.get_speed()

        if self.active_mode == "Continuous":
            interval = clamp(0.24 - speed * 0.014, 0.06, 0.24)
            if now - self.mode_last_tick >= interval:
                self.send_rumble(left_base, right_base, int(interval * 1000) + 90)
                self.mode_last_tick = now

        elif self.active_mode == "Pulse":
            interval = clamp(0.34 - speed * 0.020, 0.08, 0.30)
            if now - self.mode_last_tick >= interval:
                self.mode_toggle = not self.mode_toggle
                if self.mode_toggle:
                    self.send_rumble(left_base, right_base, int(interval * 600 + 70))
                else:
                    self.safe_stop_rumble()
                self.mode_last_tick = now

        elif self.active_mode == "Wave":
            interval = 0.08
            if now - self.mode_last_tick >= interval:
                self.mode_phase += 0.32 * (0.45 + speed / 8.0)
                left = ((math.sin(self.mode_phase) + 1.0) / 2.0) * left_base
                right = ((math.sin(self.mode_phase + math.pi) + 1.0) / 2.0) * right_base
                self.send_rumble(left, right, 120)
                self.mode_last_tick = now

        elif self.active_mode == "Alternating":
            interval = clamp(0.22 - speed * 0.013, 0.05, 0.22)
            if now - self.mode_last_tick >= interval:
                self.mode_toggle = not self.mode_toggle
                if self.mode_toggle:
                    self.send_rumble(left_base, 0.0, int(interval * 1000) + 90)
                else:
                    self.send_rumble(0.0, right_base, int(interval * 1000) + 90)
                self.mode_last_tick = now

    def decay_levels(self):
        now = time.time()
        dt = now - self.last_decay
        self.last_decay = now

        decay = max(0.0, 1.0 - dt * 4.7)
        self.current_left *= decay
        self.current_right *= decay

    def control_loop(self):
        pygame.event.pump()

        now = time.time()
        if self.active_mode and self.joystick:
            try:
                self.run_mode_tick(now)
            except Exception as exc:
                self.set_status(f"Runtime error: {exc}", tone="bad")
                self.stop_mode()

        self.decay_levels()
        self.after(24, self.control_loop)

    def ui_animation_loop(self):
        self.ui_anim_phase += 0.06
        t = (math.sin(self.ui_anim_phase) + 1.0) / 2.0

        if self.active_mode:
            strength = 0.22 + 0.20 * t
        else:
            strength = 0.06 + 0.08 * t

        border_glow = lerp_color(COLORS["border"], COLORS["accent"], strength)
        soft_glow = lerp_color(COLORS["border"], COLORS["accent"], strength * 0.7)

        self.panel.configure(border_color=border_glow)
        self.visual_card.configure(border_color=border_glow)
        self.status_bar.configure(border_color=soft_glow)

        if self.active_mode:
            pulse_text = lerp_color(COLORS["muted"], COLORS["accent"], 0.35 + 0.55 * t)
            self.label_state.configure(text_color=pulse_text)

        self.after(60, self.ui_animation_loop)

    def visualizer_loop(self):
        width = max(40, self.canvas.winfo_width())
        height = max(40, self.canvas.winfo_height())

        self.canvas.delete("all")
        self.canvas.create_rectangle(0, 0, width, height, fill=COLORS["canvas_bg"], outline="")

        step = 28
        for x in range(0, width + 1, step):
            self.canvas.create_line(x, 0, x, height, fill=COLORS["canvas_grid"], width=1)
        for y in range(0, height + 1, step):
            self.canvas.create_line(0, y, width, y, fill=COLORS["canvas_grid"], width=1)

        self.visual_phase += 0.12 + (self.get_speed() / 120.0)

        padding = 16
        gap = 3
        usable_w = width - padding * 2
        bar_w = max(3, (usable_w - gap * (self.bar_count - 1)) / self.bar_count)
        max_h = height - 34

        for i in range(self.bar_count):
            level = self.current_left if i < self.bar_count // 2 else self.current_right
            wobble = (math.sin(self.visual_phase + i * 0.45) + 1.0) / 2.0
            noise = random.uniform(0.0, 0.08)
            target = clamp(level * 0.85 + level * wobble * 0.35 + noise * level, 0.0, 1.0)

            self.bar_values[i] = self.bar_values[i] * 0.72 + target * 0.28
            h = 6 + self.bar_values[i] * max_h

            x0 = padding + i * (bar_w + gap)
            x1 = x0 + bar_w
            y1 = height - 10
            y0 = y1 - h

            mix = i / max(1, self.bar_count - 1)
            color = lerp_color("#1f2a3a", COLORS["bar"], 0.35 + mix * 0.65)
            self.canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="")

        split_x = width / 2
        self.canvas.create_line(split_x, 0, split_x, height, fill="#2f3948", width=1)

        self.after(33, self.visualizer_loop)

    def on_space(self, _event=None):
        if self.active_mode:
            self.stop_mode()
        else:
            self.start_mode()

    def on_stop_shortcut(self, _event=None):
        self.stop_mode()

    def on_refresh_shortcut(self, _event=None):
        self.manual_refresh()

    def on_close(self):
        self.stop_mode()
        self.destroy()


if __name__ == "__main__":
    app = GamepadVibrationTester()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
