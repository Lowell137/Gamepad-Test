"""Sade, tek sayfalık gamepad titreşim testi arayüzü.

PyQt6 + qFluentWidgets kullanır. Titreşim, uygulama arka planda veya
minimize edilmiş olsa da devam eder.
"""

import ctypes
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes

# Bu ayarlar SDL_Init (pygame.init) sırasında okunur; pygame import
# edilmeden önce yapılmalı.
os.environ["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] = "1"

# Windows'ta SDL, XInput kolunu RAWINPUT sürücüsüyle açıp titreşimi
# Windows.Gaming.Input (WGI) üzerinden gönderiyor. WGI titreşimi arka planda
# kapatıyor. RAWINPUT'u devre dışı bırakınca SDL saf XInput sürücüsünü
# kullanıyor; XInputSetState arka planda da çalışıyor (SDL kaynak kodu:
# "Prefer XInput over WGI because it allows rumble in the background").
os.environ["SDL_JOYSTICK_RAWINPUT"] = "0"
os.environ["SDL_JOYSTICK_WGI"] = "0"

import pygame
from PyQt6.QtCore import Qt, QTimer, QRect, QEvent
from PyQt6.QtGui import QColor, QPainter, QPen, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
)

from qfluentwidgets.common.style_sheet import isDarkTheme
from qfluentwidgets import (
    FluentWindow,
    FluentIcon,
    CardWidget,
    ElevatedCardWidget,
    ComboBox,
    Slider,
    PrimaryPushButton,
    PushButton,
    CaptionLabel,
    StrongBodyLabel,
    InfoBar,
    setTheme,
    setThemeColor,
    Theme,
)

HELPER_FLAG = "--rumble-helper"

if HELPER_FLAG not in sys.argv:
    pygame.init()
    pygame.joystick.init()

ACCENT = "#62a0ea"
BAR_COLOR = "#7eb6ff"

MODE_INFO = {
    "Continuous": "Sabit titreşim",
    "Pulse": "Belirli aralıklarla darbe",
    "Wave": "Yumuşak dalga modülasyonu",
    "Alternating": "Sağ-sol sırayla",
}


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


def to_qcolor(hex_color):
    return QColor(
        int(hex_color[1:3], 16),
        int(hex_color[3:5], 16),
        int(hex_color[5:7], 16),
    )


class XINPUT_VIBRATION(ctypes.Structure):
    _fields_ = [
        ("wLeftMotorSpeed", wintypes.WORD),
        ("wRightMotorSpeed", wintypes.WORD),
    ]


def run_rumble_helper(state_path):
    """Penceresiz süreç: XInputSetState'i sürekli yeniden gönderir.

    Windows 11, odağı olmayan GUI sürecinin titreşimini sıfırlıyor. Penceresi
    olmayan bir süreçten gönderilen XInputSetState ise arka planda da çalışıyor.
    Arayüz modu hesaplayıp hedef seviyeleri state_path dosyasına yazar; bu
    süreç dosyayı 15 ms'de bir okuyup motorlara uygular.
    """
    xinput = ctypes.WinDLL("xinput1_4.dll")
    xinput.XInputSetState.argtypes = [
        wintypes.DWORD,
        ctypes.POINTER(XINPUT_VIBRATION),
    ]
    xinput.XInputSetState.restype = wintypes.DWORD

    last_state = None
    last_update = time.time()

    while True:
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            last_update = time.time()
        except Exception:
            data = last_state

        if data is None:
            time.sleep(0.015)
            continue

        if data.get("stop"):
            break

        # Arayüz kapanırsa yardımcı süreç de kendiliğinden çıkar.
        if time.time() - last_update > 2.0:
            break

        slot = int(data.get("slot", 0)) & 0x3
        left = clamp(float(data.get("left", 0.0)), 0.0, 1.0)
        right = clamp(float(data.get("right", 0.0)), 0.0, 1.0)
        vibration = XINPUT_VIBRATION(
            int(left * 65535),
            int(right * 65535),
        )
        xinput.XInputSetState(slot, ctypes.byref(vibration))
        last_state = data
        time.sleep(0.015)

    silent = XINPUT_VIBRATION(0, 0)
    for slot in range(4):
        xinput.XInputSetState(slot, ctypes.byref(silent))
    try:
        os.remove(state_path)
    except OSError:
        pass


class VisualizerWidget(QWidget):
    """Titreşim seviyesini gösteren basit çubuk görselleştirici."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bar_count = 36
        self.bar_values = [0.0] * self.bar_count
        self.current_left = 0.0
        self.current_right = 0.0
        self.phase = 0.0
        self.setMinimumHeight(150)
        self.setSizePolicy(
            self.sizePolicy().Policy.Expanding,
            self.sizePolicy().Policy.Expanding,
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = max(40, self.width())
        height = max(40, self.height())

        painter.fillRect(0, 0, width, height, QColor("#111318"))

        grid_pen = QPen(QColor("#1e242d"))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        for x in range(0, width + 1, 28):
            painter.drawLine(x, 0, x, height)
        for y in range(0, height + 1, 28):
            painter.drawLine(0, y, width, y)

        padding, gap = 16, 3
        bar_w = max(3, (width - padding * 2 - gap * (self.bar_count - 1)) / self.bar_count)
        max_h = height - 30

        for i in range(self.bar_count):
            level = self.current_left if i < self.bar_count // 2 else self.current_right
            wobble = (math.sin(self.phase + i * 0.45) + 1.0) / 2.0
            noise = random.uniform(0.0, 0.08)
            target = clamp(level * 0.85 + level * wobble * 0.35 + noise * level, 0.0, 1.0)
            self.bar_values[i] = self.bar_values[i] * 0.72 + target * 0.28

            h = 6 + self.bar_values[i] * max_h
            x0 = padding + i * (bar_w + gap)
            y1 = height - 10
            y0 = y1 - h
            mix = i / max(1, self.bar_count - 1)
            color = lerp_color("#1f2a3a", BAR_COLOR, 0.35 + mix * 0.65)
            painter.fillRect(
                QRect(int(x0), int(y0), int(bar_w + 1), int(y1 - y0)), QColor(color)
            )

        split_pen = QPen(QColor("#2f3948"))
        split_pen.setWidth(1)
        painter.setPen(split_pen)
        painter.drawLine(int(width / 2), 0, int(width / 2), height)
        painter.end()


class TesterInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("testerInterface")

        self.joystick = None
        self.joysticks_map = {}
        self.last_device_count = -1

        self.active_mode = None
        self.mode_last_tick = 0.0
        self.mode_phase = 0.0
        self.mode_toggle = False

        self.current_left = 0.0
        self.current_right = 0.0
        self.last_decay = time.time()

        self.state_path = os.path.join(
            tempfile.gettempdir(), f"gamepad_haptics_{os.getpid()}.json"
        )
        self.helper_proc = None

        self._build_ui()
        self._setup_timers()
        self.refresh_devices()
        self.window().installEventFilter(self)

        self.shortcut_map = {}
        sc_start = QShortcut(QKeySequence(Qt.Key.Key_Space), self.window())
        sc_start.activated.connect(self.toggle_mode)
        self.shortcut_map["Space"] = sc_start
        sc_stop = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.window())
        sc_stop.activated.connect(self.stop_mode)
        self.shortcut_map["Escape"] = sc_stop

    # ---------- arayüz ----------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        # Cihaz
        device_card = CardWidget(self)
        device_layout = QVBoxLayout(device_card)
        device_layout.setContentsMargins(14, 10, 14, 12)
        device_layout.setSpacing(6)
        device_layout.addWidget(StrongBodyLabel("Cihaz", device_card))

        device_row = QHBoxLayout()
        self.device_combo = ComboBox(device_card)
        self.device_combo.addItems(["Cihaz yok"])
        self.device_combo.setMinimumWidth(260)
        self.device_combo.currentTextChanged.connect(self.on_device_select)
        device_row.addWidget(self.device_combo, 1)

        self.btn_refresh = PushButton(FluentIcon.SYNC, "Yenile", device_card)
        self.btn_refresh.clicked.connect(self.refresh_devices)
        device_row.addWidget(self.btn_refresh)
        device_layout.addLayout(device_row)
        root.addWidget(device_card)

        # Kontroller
        control_card = CardWidget(self)
        control_layout = QVBoxLayout(control_card)
        control_layout.setContentsMargins(14, 10, 14, 14)
        control_layout.setSpacing(8)

        mode_row = QHBoxLayout()
        mode_row.addWidget(StrongBodyLabel("Mod", control_card))
        self.mode_combo = ComboBox(control_card)
        self.mode_combo.addItems(list(MODE_INFO.keys()))
        self.mode_combo.currentTextChanged.connect(self.on_mode_change)
        mode_row.addWidget(self.mode_combo)
        self.mode_desc = CaptionLabel(MODE_INFO[self.mode_combo.currentText()], control_card)
        mode_row.addWidget(self.mode_desc)
        mode_row.addStretch(1)
        control_layout.addLayout(mode_row)

        sliders = QGridLayout()
        sliders.setHorizontalSpacing(16)
        sliders.setVerticalSpacing(2)
        self.label_left = StrongBodyLabel("Sol %100", control_card)
        self.label_right = StrongBodyLabel("Sağ %100", control_card)
        sliders.addWidget(self.label_left, 0, 0)
        sliders.addWidget(self.label_right, 0, 1)

        self.slider_left = Slider(Qt.Orientation.Horizontal, control_card)
        self.slider_left.setRange(0, 100)
        self.slider_left.setValue(100)
        self.slider_left.valueChanged.connect(self.update_left)
        sliders.addWidget(self.slider_left, 1, 0)

        self.slider_right = Slider(Qt.Orientation.Horizontal, control_card)
        self.slider_right.setRange(0, 100)
        self.slider_right.setValue(100)
        self.slider_right.valueChanged.connect(self.update_right)
        sliders.addWidget(self.slider_right, 1, 1)
        control_layout.addLayout(sliders)

        buttons = QHBoxLayout()
        self.btn_toggle = PrimaryPushButton(FluentIcon.PLAY_SOLID, "Başlat", control_card)
        self.btn_toggle.clicked.connect(self.toggle_mode)
        buttons.addWidget(self.btn_toggle, 1)

        self.btn_oneshot = PushButton(FluentIcon.IOT, "1 sn test", control_card)
        self.btn_oneshot.clicked.connect(self.one_shot)
        buttons.addWidget(self.btn_oneshot, 1)
        control_layout.addLayout(buttons)

        root.addWidget(control_card)

        # Görselleştirici
        visual_card = ElevatedCardWidget(self)
        visual_layout = QVBoxLayout(visual_card)
        visual_layout.setContentsMargins(10, 10, 10, 10)
        self.visualizer = VisualizerWidget(visual_card)
        visual_layout.addWidget(self.visualizer)
        root.addWidget(visual_card, 1)

        # Durum
        status_row = QHBoxLayout()
        self.label_status = CaptionLabel("Hazır", self)
        self.label_state = CaptionLabel("Boşta", self)
        status_row.addWidget(self.label_status)
        status_row.addStretch(1)
        status_row.addWidget(self.label_state)
        root.addLayout(status_row)

    def _setup_timers(self):
        self.control_timer = QTimer(self)
        self.control_timer.setInterval(24)
        # PreciseTimer minimize edilince yavaşlatılmaz; titreşim canlı tutulur.
        self.control_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.control_timer.timeout.connect(self.control_loop)
        self.control_timer.start()

        self.device_timer = QTimer(self)
        self.device_timer.setInterval(800)
        self.device_timer.timeout.connect(self.device_watch_loop)
        self.device_timer.start()

        self.visual_timer = QTimer(self)
        self.visual_timer.setInterval(33)
        self.visual_timer.timeout.connect(self.visualizer_loop)
        self.visual_timer.start()

    # ---------- durum ----------
    def set_status(self, text, tone="muted"):
        self.label_status.setText(text)
        if tone == "ok":
            InfoBar.success("Durum", text, duration=2000, parent=self.window())
        elif tone == "warn":
            InfoBar.warning("Durum", text, duration=2000, parent=self.window())
        elif tone == "bad":
            InfoBar.error("Durum", text, duration=2000, parent=self.window())

    def on_mode_change(self, _text):
        self.mode_desc.setText(MODE_INFO[self.mode_combo.currentText()])

    def update_left(self, value):
        self.label_left.setText(f"Sol %{int(value)}")

    def update_right(self, value):
        self.label_right.setText(f"Sağ %{int(value)}")

    def get_levels(self):
        return self.slider_left.value() / 100.0, self.slider_right.value() / 100.0

    # ---------- cihaz ----------
    def refresh_devices(self):
        pygame.event.pump()
        pygame.joystick.quit()
        pygame.joystick.init()

        self.joystick = None
        self.joysticks_map = {}
        names = []
        count = pygame.joystick.get_count()
        self.last_device_count = count

        if count == 0:
            self.device_combo.blockSignals(True)
            self.device_combo.clear()
            self.device_combo.addItems(["Cihaz yok"])
            self.device_combo.blockSignals(False)
            self.set_status("Cihaz bulunamadı", tone="bad")
            return

        previous = self.device_combo.currentText()
        for i in range(count):
            try:
                joystick = pygame.joystick.Joystick(i)
                joystick.init()
                name = f"{i}: {joystick.get_name()}"
                names.append(name)
                self.joysticks_map[name] = joystick
            except Exception:
                continue

        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItems(names)
        self.device_combo.blockSignals(False)

        if previous in self.joysticks_map:
            self.device_combo.setCurrentText(previous)
        elif names:
            self.device_combo.setCurrentIndex(0)
            self.on_device_select(names[0])

    def on_device_select(self, choice):
        self.joystick = self.joysticks_map.get(choice)
        if self.joystick:
            self.set_status(f"Seçildi: {choice}")

    def device_watch_loop(self):
        count = pygame.joystick.get_count()
        if count == self.last_device_count:
            return
        self.last_device_count = count
        self.refresh_devices()

    # ---------- titreşim ----------
    def _write_state(self, left, right, stop=False):
        """Hedef motor seviyelerini yardımcı sürecin okuduğu dosyaya yazar."""
        data = {
            "slot": int(self.joystick.get_id()) if self.joystick else 0,
            "left": clamp(left, 0.0, 1.0),
            "right": clamp(right, 0.0, 1.0),
            "stop": stop,
        }
        tmp = self.state_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.state_path)
        except OSError:
            pass

    def _start_helper(self):
        if self.helper_proc and self.helper_proc.poll() is None:
            return
        self._write_state(0.0, 0.0)
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, HELPER_FLAG, self.state_path]
        else:
            pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            if not os.path.exists(pythonw):
                pythonw = sys.executable
            cmd = [pythonw, os.path.abspath(__file__), HELPER_FLAG, self.state_path]

        flags = 0
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        self.helper_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )

    def _stop_helper(self):
        self._write_state(0.0, 0.0, stop=True)
        proc = self.helper_proc
        if proc is not None:
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                proc.terminate()
            self.helper_proc = None
        try:
            os.remove(self.state_path)
        except OSError:
            pass

    def _stop_helper_if_idle(self):
        if not self.active_mode:
            self._stop_helper()

    def send_rumble(self, left, right, duration_ms):
        left = clamp(left, 0.0, 1.0)
        right = clamp(right, 0.0, 1.0)
        self._write_state(left, right)
        self.current_left = left
        self.current_right = right

    def safe_stop_rumble(self):
        self._write_state(0.0, 0.0)

    def toggle_mode(self):
        self.stop_mode() if self.active_mode else self.start_mode()

    def start_mode(self):
        if not self.joystick:
            self.set_status("Önce bir cihaz seç", tone="warn")
            return
        self.active_mode = self.mode_combo.currentText()
        self.mode_last_tick = 0.0
        self.mode_phase = 0.0
        self.mode_toggle = False
        self._start_helper()
        self.btn_toggle.setText("Durdur")
        self.btn_toggle.setIcon(FluentIcon.PAUSE_BOLD)
        self.label_state.setText(f"Mod: {self.active_mode}")
        self.set_status(f"{self.active_mode} başlatıldı")

    def stop_mode(self):
        if self.active_mode:
            self.set_status("Durduruldu")
        self.active_mode = None
        self.mode_toggle = False
        self.current_left = 0.0
        self.current_right = 0.0
        self.safe_stop_rumble()
        self._stop_helper()
        self.btn_toggle.setText("Başlat")
        self.btn_toggle.setIcon(FluentIcon.PLAY_SOLID)
        self.label_state.setText("Boşta")

    def one_shot(self):
        if not self.joystick:
            self.set_status("Önce bir cihaz seç", tone="warn")
            return
        left, right = self.get_levels()
        try:
            self._start_helper()
            self.send_rumble(left, right, 1000)
            QTimer.singleShot(1000, self._stop_helper_if_idle)
            self.set_status("1 saniyelik test gönderildi")
        except Exception as exc:
            self.set_status(f"Titreşim hatası: {exc}", tone="bad")

    def run_mode_tick(self, now):
        left_base, right_base = self.get_levels()
        speed = 5

        if self.active_mode == "Continuous":
            interval = clamp(0.18 - speed * 0.010, 0.06, 0.18)
            if now - self.mode_last_tick >= interval:
                # Süresiz titreşim: zamanlayıcı gecikse bile motorlar durmaz.
                self.send_rumble(left_base, right_base, 0)
                self.mode_last_tick = now

        elif self.active_mode == "Pulse":
            interval = clamp(0.34 - speed * 0.020, 0.08, 0.30)
            if now - self.mode_last_tick >= interval:
                self.mode_toggle = not self.mode_toggle
                if self.mode_toggle:
                    self.send_rumble(left_base, right_base, int(interval * 600) + 250)
                else:
                    self.safe_stop_rumble()
                self.mode_last_tick = now

        elif self.active_mode == "Wave":
            interval = 0.05
            if now - self.mode_last_tick >= interval:
                self.mode_phase += 0.32 * (0.45 + speed / 8.0)
                left = ((math.sin(self.mode_phase) + 1.0) / 2.0) * left_base
                right = ((math.sin(self.mode_phase + math.pi) + 1.0) / 2.0) * right_base
                self.send_rumble(left, right, 250)
                self.mode_last_tick = now

        elif self.active_mode == "Alternating":
            interval = clamp(0.20 - speed * 0.012, 0.06, 0.20)
            if now - self.mode_last_tick >= interval:
                self.mode_toggle = not self.mode_toggle
                if self.mode_toggle:
                    self.send_rumble(left_base, 0.0, int(interval * 1000) + 250)
                else:
                    self.send_rumble(0.0, right_base, int(interval * 1000) + 250)
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
        if self.active_mode and self.joystick:
            try:
                self.run_mode_tick(time.time())
            except Exception as exc:
                self.set_status(f"Çalışma hatası: {exc}", tone="bad")
                self.stop_mode()
        self.decay_levels()
        self.visualizer.current_left = self.current_left
        self.visualizer.current_right = self.current_right

    def visualizer_loop(self):
        self.visualizer.phase += 0.15
        self.visualizer.update()

    def eventFilter(self, obj, event):
        if obj is self and event.type() in (
            QEvent.Type.WindowStateChange,
            QEvent.Type.ApplicationStateChange,
        ):
            if self.active_mode:
                # Odak/minimize değişiminden sonra titreşimi hemen yenile.
                self.mode_last_tick = 0.0
        return super().eventFilter(obj, event)

    def cleanup(self):
        for timer in (self.control_timer, self.device_timer, self.visual_timer):
            timer.stop()
        self.stop_mode()
        pygame.joystick.quit()


class GamepadHapticsWindow(FluentWindow):
    """Tek sayfalık pencere; qFluentWidgets'in özel başlık çubuğunu kullanır."""

    def __init__(self):
        super().__init__()
        setTheme(Theme.DARK)
        setThemeColor(to_qcolor(ACCENT))

        self.setWindowTitle("Gamepad Haptics")
        self.resize(720, 540)
        self.setMinimumSize(580, 440)

        self.tester = TesterInterface(self)
        self.addSubInterface(self.tester, FluentIcon.GAME, "Gamepad Haptics")

        # Sade arayüzde gezinme paneli yok; özel title bar kalır.
        self.navigationInterface.hide()

        # Başlık yazısını sola yasla (FluentWindow normalde 46 px boşluk bırakır).
        self.titleBar.hBoxLayout.setContentsMargins(12, 0, 0, 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.titleBar.move(0, 0)
        self.titleBar.resize(self.width(), self.titleBar.height())

    def showEvent(self, e):
        super().showEvent(e)
        # Mica/şeffaf arka plan ilk açılışta bazen tutmuyor; kullanıcı
        # minimize edip geri açmak zorunda kalmasın diye kısa gecikmeyle
        # yeniden uyguluyoruz (tema moduna dokunmadan).
        if self.isMicaEffectEnabled():
            QTimer.singleShot(100, self._reapply_mica)

    def _reapply_mica(self):
        if not self.isVisible() or not self.isMicaEffectEnabled():
            return
        self.windowEffect.setMicaEffect(int(self.winId()), isDarkTheme())
        self.setBackgroundColor(QColor(0, 0, 0, 0))
        self.update()

    def closeEvent(self, event):
        self.tester.cleanup()
        super().closeEvent(event)


if __name__ == "__main__":
    if HELPER_FLAG in sys.argv:
        index = sys.argv.index(HELPER_FLAG)
        state_path = sys.argv[index + 1] if len(sys.argv) > index + 1 else ""
        if state_path:
            run_rumble_helper(state_path)
    else:
        app = QApplication(sys.argv)
        window = GamepadHapticsWindow()
        window.show()
        sys.exit(app.exec())
