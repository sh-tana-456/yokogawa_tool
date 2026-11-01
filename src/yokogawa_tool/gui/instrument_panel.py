"""Front-panel controls with debounced automatic apply and hardware readback."""
from PySide6 import QtCore, QtWidgets as W
import pyqtgraph as pg
from yokogawa_tool.acquisition.settings import scalar, settings_commands, RECORD_LENGTHS, HIGH_RES_RECORD_LENGTHS
from yokogawa_tool.gui.quantity_control import QuantityControl

GROUP_KEYS = {"time": ("tdiv", "acquire_mode", "record_length"),
              "channel": ("display", "probe", "vdiv", "offset", "position", "coupling", "bandwidth", "invert"),
              "trigger": ("trigger_mode", "source", "slope", "level", "delay")}


def combo(items):
    widget = W.QComboBox()
    for label, value in items:
        widget.addItem(label, value)
    return widget


class StatusLabel(W.QLabel):
    """Reserve three lines regardless of message length or wrapping."""
    def __init__(self, text):
        super().__init__(text)
        self.setTextFormat(QtCore.Qt.PlainText)
        self.setWordWrap(True)
        self.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.setSizePolicy(W.QSizePolicy.Ignored, W.QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.setToolTip(text)
        self.reserve_height()

    def reserve_height(self):
        self.setFixedHeight(self.fontMetrics().lineSpacing() * 3 + 12)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QtCore.QEvent.FontChange, QtCore.QEvent.StyleChange):
            self.reserve_height()

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)


class InstrumentPanel(W.QWidget):
    requested = QtCore.Signal(str, object)
    live_requested = QtCore.Signal(bool)
    invalidated = QtCore.Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.loaded_channel = None
        self.loaded_host = None
        self.running = None
        self._run_pending = False
        self._updating = True
        self._busy = False
        self._loaded = False
        self._pending = {}
        self._confirmed = {}
        self._refresh_requested = False
        self._lcd_pending = None
        self._sampling = {}
        self._channel_sampling = {}
        self._last_waveforms = {}
        self.sync_timer = QtCore.QTimer(self)
        self.sync_timer.setSingleShot(True)
        self.sync_timer.setInterval(250)
        self.sync_timer.timeout.connect(self.flush_pending)
        outer = W.QVBoxLayout(self)
        self.status = StatusLabel("未接続 · このタブを開くと設定を読み込みます")
        self.status.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        outer.addWidget(self.status)
        self.acquisition_info = StatusLabel('Fs (setting): — | T/div: —\nCH1 V/div: — | Record: —\nRead: — pts | Fs (record): —')
        self.acquisition_info.setStyleSheet('font-size: 11px;')
        self.acquisition_info.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        outer.addWidget(self.acquisition_info)
        self.controls = W.QWidget()
        layout = W.QVBoxLayout(self.controls)
        layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.controls)
        self.command_buttons = []
        self.setting_groups = {}
        self.fields = {}

        connection = W.QGroupBox("接続・測定")
        form = W.QFormLayout(connection)
        self.host = W.QLineEdit(str(settings.value("host", "10.0.10.16")))
        self.port = W.QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(10001)
        self.username = W.QLineEdit(str(settings.value("username", "anonymous")))
        self.password = W.QLineEdit()
        self.password.setEchoMode(W.QLineEdit.Password)
        for label, widget in (("IP / ホスト", self.host), ("ポート", self.port),
                              ("ユーザー", self.username), ("パスワード", self.password)):
            form.addRow(label, widget)
        self.refresh_button = self.action_button("再接続・状態更新", "READ_SETTINGS")
        form.addRow(self.refresh_button)
        form.addRow(self.action_button("停止中の波形を読み出す", "CAPTURE", True))
        self.live_button = W.QPushButton("実機に接続して波形表示")
        self.live_button.setCheckable(True)
        self.live_button.setMinimumHeight(32)
        self.live_button.setProperty("role", "capture")
        self.live_button.toggled.connect(self.live_requested)
        form.addRow(self.live_button)
        self.blank_display = W.QCheckBox("操作中は本体LCDを消灯")
        self.blank_display.setChecked(settings.value("blank_instrument_display", True, type=bool))
        self.blank_display.setToolTip("本体のバックライトを消灯し、接続解除時に接続前の状態へ戻します。測定は継続します。")
        def display_preference_changed(enabled):
            settings.setValue("blank_instrument_display", enabled)
            if self._loaded:
                self._refresh_requested = True
                self.sync_timer.start(0)
        self.blank_display.toggled.connect(display_preference_changed)
        form.addRow(self.blank_display)
        self.live_mode = combo([("プレビュー優先（短時間STOP）", True)])
        self.live_mode.setParent(self)
        self.live_mode.hide()
        self.live_mode.setSizeAdjustPolicy(W.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.live_mode.setMinimumContentsLength(8)
        self.live_mode.setToolTip("プレビュー優先: 波形転送時だけ停止し、転送後にRUNへ復帰します。")
        self.live_interval = W.QSpinBox()
        self.live_interval.setRange(100, 10000)
        self.live_interval.setSingleStep(100)
        self.live_interval.setValue(settings.value("live_interval_ms", 100, type=int))
        self.live_interval.valueChanged.connect(lambda value: settings.setValue("live_interval_ms", value))
        self.live_interval.setSuffix(" ms")
        form.addRow("更新周期（目安）", self.live_interval)
        live_note = W.QLabel("転送中だけ短時間STOPします。\n平均化は再開時にリセットされます。\n更新周期は次回起動時も保持します。")
        live_note.setWordWrap(True)
        live_note.setProperty("muted", True)
        form.addRow(live_note)
        row = W.QHBoxLayout()
        self.run_button = self.action_button("RUN / STOP（未接続）", "TOGGLE_RUN")
        self.run_button.setMinimumHeight(48)
        self.run_button.setCheckable(True)
        row.addWidget(self.run_button, 2)
        form.addRow(row)
        self.single_button = self.action_button("単発", "SINGLE")
        form.addRow(self.single_button)
        extra_actions = W.QWidget()
        row = W.QHBoxLayout(extra_actions)
        row.addWidget(self.action_button("オートセットアップ", "AUTO_SETUP"))
        row.addWidget(self.action_button("LOCAL", "LOCAL"))
        form.addRow(extra_actions)
        note = W.QLabel("本体: MISC → Remote Cntl → Network\n取得は表示ONのCH。RUN・単発は本体の測定を開始します。")
        note.setWordWrap(True)
        note.setProperty("muted", True)
        form.addRow(note)
        self.details = W.QWidget()
        details_form = W.QFormLayout(self.details)
        details_form.setContentsMargins(0, 0, 0, 0)
        for widget in (self.host, self.port, self.username, self.password, self.refresh_button,
                       self.blank_display, self.live_interval, live_note, self.single_button, extra_actions, note):
            taken = form.takeRow(widget)
            label = taken.labelItem.widget() if taken.labelItem is not None else None
            if label is not None:
                details_form.addRow(label, widget)
            else:
                details_form.addRow(widget)
        self.lcd_state = W.QLabel('LCD状態: 未読込')
        details_form.addRow(self.lcd_state)
        lcd_row = W.QHBoxLayout()
        for title, action in (('LCD ON', 'LCD_ON'), ('LCD OFF', 'LCD_OFF'), ('状態', 'LCD_READ')):
            lcd_row.addWidget(self.action_button(title, action))
        details_form.addRow(lcd_row)
        self.lcd_brightness = W.QSpinBox()
        self.lcd_brightness.setRange(1, 4)
        self.lcd_brightness.setValue(2)
        details_form.addRow('明るさ設定 1〜4', self.lcd_brightness)
        details_form.addRow(self.action_button('明るさを反映', 'LCD_BRIGHTNESS'))
        self.details_toggle = W.QToolButton()
        self.details_toggle.setText('接続・詳細操作を表示')
        self.details_toggle.setCheckable(True)
        self.details_toggle.toggled.connect(self.details.setVisible)
        form.addRow(self.details_toggle)
        form.addRow(self.details)
        self.details.hide()
        layout.addWidget(connection)
        self.fine = W.QCheckBox("微調整（刻みを1/10）")
        self.fine.setToolTip("オフセット・縦位置・トリガレベル・遅延を細かく調整します")
        self.fine.toggled.connect(self.set_fine)
        layout.addWidget(self.fine)

        time_group = W.QGroupBox("時間軸・取得")
        form = W.QFormLayout(time_group)
        self.add_text(form, "T/div [s]", "tdiv", "例: 1ms / 1e-3")
        self.fields["acquire_mode"] = combo([("Normal", "NORMAL"), ("Envelope", "ENVELOPE"), ("Average", "AVERAGE")])
        form.addRow("取得モード", self.fields["acquire_mode"])
        self.fields['record_length'] = combo([(f'{n//1000}k' if n < 1000000 else f'{n//1000000}M', str(n)) for n in RECORD_LENGTHS])
        self.fields['record_length'].setToolTip('DL1640の固定記録長。高分解能時の最大は4M、通常は8M。5k・20k等は指定できません。')
        form.addRow('レコード長 [点]', self.fields['record_length'])
        self.setting_groups["time"] = time_group
        layout.addWidget(time_group)

        channel_group = W.QGroupBox("CHの設定（実機）")
        form = W.QFormLayout(channel_group)
        self.channel = combo([(f"CH{i}", i) for i in range(1, 5)])
        form.addRow("対象CH", self.channel)
        self.channel.currentIndexChanged.connect(self.channel_changed)
        self.fields["display"] = W.QCheckBox("CHを表示")
        form.addRow(self.fields["display"])
        self.fields["probe"] = combo([(f"{n}:1", n) for n in ("1", "10", "100", "1000")] + [("電流 C10", "C10"), ("電流 C100", "C100")])
        form.addRow("プローブ", self.fields["probe"])
        self.add_text(form, "感度 [V/div・A/div]", "vdiv", "例: 500mV / 0.5")
        self.add_text(form, "オフセット [V・A]", "offset", "例: 0V")
        self.add_text(form, "縦位置 [div]", "position", "−4〜4")
        self.fields["coupling"] = combo([(v, v) for v in ("DC", "AC", "GND")])
        form.addRow("入力結合", self.fields["coupling"])
        self.fields["bandwidth"] = combo([("FULL", "FULL"), ("20 MHz", "20E6"), ("1.28 MHz", "1.28E6"),
            ("640 kHz", "640E3"), ("320 kHz", "320E3"), ("160 kHz", "160E3"), ("80 kHz", "80E3"), ("20 kHz", "20E3"), ("10 kHz", "10E3")])
        form.addRow("帯域制限", self.fields["bandwidth"])
        self.fields["invert"] = W.QCheckBox("極性を反転")
        form.addRow(self.fields["invert"])
        self.setting_groups["channel"] = channel_group
        layout.addWidget(channel_group)

        trigger_group = W.QGroupBox("エッジトリガ（SIMPLE）")
        form = W.QFormLayout(trigger_group)
        self.trigger_type = W.QLabel("現在のタイプ: 未読込")
        form.addRow(self.trigger_type)
        self.fields["trigger_mode"] = combo([(v, v) for v in ("AUTO", "ALEVEL", "NORMAL", "SINGLE", "NSINGLE")])
        form.addRow("モード", self.fields["trigger_mode"])
        self.fields["source"] = combo([(f"CH{i}", str(i)) for i in range(1, 5)] + [("外部 EXT", "EXTERNAL"), ("LINE", "LINE")])
        form.addRow("ソース", self.fields["source"])
        self.fields["slope"] = combo([("立ち上がり", "RISE"), ("立ち下がり", "FALL"), ("両方", "BOTH")])
        form.addRow("スロープ", self.fields["slope"])
        self.add_text(form, "レベル [V・A]", "level", "例: 1.5V")
        self.add_text(form, "遅延 [s]", "delay", "例: 0s / 10us")
        self.fields["source"].currentIndexChanged.connect(self.source_changed)
        self.setting_groups["trigger"] = trigger_group
        note = W.QLabel("変更は自動送信し、本体の実値を再読込します。\nソース・レベル・スロープの編集でSIMPLEに切り替わります。")
        note.setWordWrap(True)
        note.setProperty("muted", True)
        form.addRow(note)
        layout.addWidget(trigger_group)
        layout.addStretch()
        for widget in (self.host, self.username, self.password):
            widget.textChanged.connect(self.invalidate)
            widget.editingFinished.connect(self.ensure_loaded)
        self.port.valueChanged.connect(self.invalidate)
        self.port.editingFinished.connect(self.ensure_loaded)
        for group, keys in GROUP_KEYS.items():
            for key in keys:
                widget = self.fields[key]
                signal = (widget.edited if isinstance(widget, QuantityControl) else
                          widget.toggled if isinstance(widget, W.QCheckBox) else widget.currentIndexChanged)
                signal.connect(lambda *args, g=group, k=key: self.field_edited(g, k))
        self._updating = False
        self.update_enabled()

    def action_button(self, text, action, accent=False):
        button = W.QPushButton(text)
        button.setProperty("accent", accent)
        button.setProperty("action", action)
        button.setProperty("role", {"READ_SETTINGS": "read", "CAPTURE": "capture", "SINGLE": "single",
                                    "AUTO_SETUP": "setup", "LOCAL": "local"}.get(action, "run"))
        button.clicked.connect(lambda: self.command(action))
        self.command_buttons.append(button)
        return button

    def add_text(self, form, label, key, placeholder):
        specs = {"tdiv": dict(low=2e-9, high=800, unit="s", engineering=True),
                 "vdiv": dict(low=.002, high=10000, unit="V|A", engineering=True),
                 "offset": dict(low=-100000, high=100000, unit="V|A", step=lambda: self.scale_step("vdiv", .5)),
                 "position": dict(low=-4, high=4, step=.1),
                 "level": dict(low=-100000, high=100000, unit="V|A", step=lambda: self.scale_step("vdiv", .5)),
                 "delay": dict(low=0, high=4, unit="s", step=lambda: self.scale_step("tdiv", .001))}
        widget = QuantityControl(**specs[key])
        widget.setPlaceholderText(placeholder)
        self.fields[key] = widget
        form.addRow(label, widget)

    def widget_value(self, key):
        widget = self.fields[key]
        return (widget.isChecked() if isinstance(widget, W.QCheckBox) else
                widget.currentData() if isinstance(widget, W.QComboBox) else widget.text())

    def scale_step(self, key, default):
        try:
            return max(abs(self.fields[key].value())*.1, 1e-12)
        except ValueError:
            return default*.1

    def set_fine(self, fine):
        for widget in self.fields.values():
            if isinstance(widget, QuantityControl):
                widget.fine = fine

    def command(self, action):
        if action.startswith('LCD_'):
            values = dict(self._lcd_pending or {})
            if action in ('LCD_ON', 'LCD_OFF'):
                self.blank_display.setChecked(False)
                values['enabled'] = action == 'LCD_ON'
            elif action == 'LCD_BRIGHTNESS':
                values['brightness'] = self.lcd_brightness.value()
            self._lcd_pending = values
            self.sync_timer.start(0)
            return
        if action == "TOGGLE_RUN":
            self.run_button.setChecked(bool(self.running))
            if self.running is not None:
                self.requested.emit(action, {"channel": self.channel.currentData()})
            return
        if self._busy or self._pending:
            return
        if action == "TOGGLE_RUN":
            self.run_button.setChecked(bool(self.running))
        if action == "READ_SETTINGS":
            self.sync_timer.stop()
            self._refresh_requested = False
        self.requested.emit(action, {"channel": self.channel.currentData()})

    def ensure_loaded(self):
        if not self._loaded and not self._busy:
            self._refresh_requested = True
            self.sync_timer.start(250)

    def field_edited(self, group, key):
        if self._updating or not self._loaded:
            return
        self._pending.setdefault(group, set()).add(key)
        self.status.setText("変更をまとめています…（操作後に自動反映）")
        self.sync_timer.start(250)
        self.update_enabled()

    def flush_pending(self):
        if self._busy:
            return
        if self._lcd_pending is not None:
            values, self._lcd_pending = self._lcd_pending, None
            self.requested.emit('LCD' if values else 'READ_LCD', values)
            return
        if self._refresh_requested:
            self._refresh_requested = False
            self.requested.emit("READ_SETTINGS", {"channel": self.channel.currentData()})
        elif self._pending:
            group = next(iter(self._pending))
            fields = self._pending.pop(group)
            values = {"channel": self.channel.currentData()}
            values['_high_resolution'] = getattr(self, '_high_resolution', False)
            values.update({key: self.widget_value(key) if key in fields else self._confirmed[key] for key in GROUP_KEYS[group]})
            try:
                settings_commands(group, values, fields)
            except (ValueError, KeyError) as exc:
                self.status.setText(f"入力値を確認してください: {exc}")
                self.update_enabled()
                return
            self.requested.emit("APPLY_" + group.upper(), dict(values, _fields=sorted(fields)))

    def update_enabled(self):
        for group in self.setting_groups.values():
            group.setEnabled(self._loaded)
        stable = not self._busy and not self._pending
        for widget in (self.host, self.port, self.username, self.password):
            widget.setEnabled(stable)
        # The channel choice is a queued read request, not a device write.
        # Disabling it on each live poll closes its dropdown while selecting.
        self.channel.setEnabled(not self._pending)
        for key in GROUP_KEYS["channel"]:
            self.fields[key].setEnabled(self._loaded and self.loaded_channel == self.channel.currentData())
        for button in self.command_buttons:
            button.setEnabled((self.running is not None if button is self.run_button else
                              bool(self.host.text().strip()) if str(button.property('action')).startswith('LCD_') else stable))
        self.source_changed()

    def channel_changed(self):
        self.loaded_channel = None
        if self._loaded and not self._updating:
            self._refresh_requested = True
            self.sync_timer.start(250)
        self.update_enabled()
        self.update_acquisition_info()

    def source_changed(self):
        enabled = self.fields["source"].currentData() != "LINE"
        self.fields["slope"].setEnabled(enabled)
        self.fields["level"].setEnabled(enabled)

    def invalidate(self):
        self.invalidated.emit()
        self.loaded_channel = None
        self.loaded_host = None
        self.running = None
        self._run_pending = False
        self._loaded = False
        self._pending.clear()
        self._lcd_pending = None
        self._confirmed.clear()
        self._sampling.clear()
        self._channel_sampling.clear()
        self._last_waveforms.clear()
        self.update_acquisition_info()
        self._refresh_requested = False
        self.sync_timer.stop()
        self.update_run_button()
        self.update_enabled()

    def set_live_state(self, enabled):
        self.live_button.blockSignals(True)
        self.live_button.setChecked(enabled)
        self.live_button.blockSignals(False)
        self.live_button.setText("実機との接続を解除" if enabled else "実機に接続して波形表示")
        self.live_button.setProperty("role", "read" if enabled else "capture")
        self.live_button.style().unpolish(self.live_button)
        self.live_button.style().polish(self.live_button)

    def set_busy(self, busy):
        self._busy = busy
        if busy:
            self.sync_timer.stop()
        self.update_enabled()
        if not busy and (self._pending or self._refresh_requested or self._lcd_pending is not None):
            self.sync_timer.start(0)

    def set_lcd_state(self, result):
        self.lcd_state.setText(f"LCD: {'ON' if result['lcd_on'] else 'OFF'} · 明るさ {result['lcd_brightness']}")
        self.lcd_brightness.setValue(result['lcd_brightness'])

    def update_acquisition_info(self):
        def number(value, unit=''):
            try:
                return pg.siFormat(scalar(value), precision=5, suffix=unit)
            except (ValueError, TypeError):
                return '—'
        channel = self.channel.currentData()
        current = self._channel_sampling.get(channel, {})
        record = self._last_waveforms.get(f'CH{channel}', {})
        unit = current.get('unit', 'V')
        text = (f"Fs (setting): {number(self._sampling.get('sample_rate'), 'Sa/s')} | "
                f"T/div: {number(self._sampling.get('tdiv'), 's')}\n"
                f"CH{channel} {unit}/div: {number(current.get('vdiv'), unit)} | "
                f"Record: {number(self._sampling.get('record_length'))}\n"
                f"Read: {record.get('points', '—')} pts | "
                f"Fs (record): {number(record.get('sample_rate'), 'Sa/s')}")
        if self.acquisition_info.text() != text:
            self.acquisition_info.setText(text)
        self.acquisition_info.setToolTip(text + '\n\nFs (setting)/Record: 最後に読み取った本体設定。'
            '\nRead/Fs (record): 最後に取得した波形の点数とサンプリングレート。'
            '\nSTOP中の設定変更では、設定と保存済み波形のレートが異なる場合があります。')

    def update_waveform_info(self, traces):
        for trace in traces:
            if trace.name not in ('CH1', 'CH2', 'CH3', 'CH4'):
                continue
            metadata = trace.metadata
            self._last_waveforms[trace.name] = {'points': len(trace.x), 'sample_rate': metadata.get('sample_rate')}
            if 'time_div' in metadata:
                self._sampling['tdiv'] = metadata['time_div']
            if 'timebase_sample_rate' in metadata:
                self._sampling['sample_rate'] = metadata['timebase_sample_rate']
            if 'vertical_div' in metadata:
                channel_info = self._channel_sampling.setdefault(int(trace.name[-1]), {})
                channel_info['vdiv'] = metadata['vertical_div']
                channel_info.setdefault('unit', trace.unit)
        self.update_acquisition_info()

    def update_run_button(self):
        self.run_button.setChecked(bool(self.running))
        text = ("■ STOP [Space]" if self.running else "▶ RUN [Space]"
                if self.running is not None else "RUN / STOP（未接続）")
        if self._run_pending:
            text += " …"
        if self.run_button.text() != text:
            self.run_button.setText(text)
        role = "stop" if self.running else "run"
        if self.run_button.property("role") != role:
            self.run_button.setProperty("role", role)
            self.run_button.style().unpolish(self.run_button)
            self.run_button.style().polish(self.run_button)
        self.run_button.setToolTip("操作待ち · 通信の区切りで実機のRUN/STOPを切り替えます" if self._run_pending
                                   else "実機の測定を開始／停止します（Space）。読み出し中も操作できます。")

    def set_run_pending(self, pending):
        self._run_pending = pending
        self.update_run_button()

    def update_settings(self, data):
        self._high_resolution = str(data.get('high_resolution', '0')).upper() in ('1', 'ON')
        record = self.fields['record_length']
        choices = HIGH_RES_RECORD_LENGTHS if self._high_resolution else RECORD_LENGTHS
        if tuple(int(record.itemData(i)) for i in range(record.count())) != choices:
            previous = record.currentData()
            blocked = record.blockSignals(True)
            record.clear()
            for n in choices:
                record.addItem(f'{n//1000}k' if n < 1000000 else f'{n//1000000}M', str(n))
            record.setCurrentIndex(max(0, record.findData(previous)))
            record.blockSignals(blocked)
        self._updating = True
        dirty = set().union(*self._pending.values()) if self._pending else set()
        for key, value in data.items():
            if key not in self.fields:
                continue
            widget = self.fields[key]
            preserve = key in dirty or (isinstance(widget, QuantityControl) and widget.editor.isModified())
            if preserve:
                current = self.widget_value(key)
                modified = isinstance(widget, QuantityControl) and widget.editor.isModified()
                committed = widget._committed if isinstance(widget, QuantityControl) else None
            if isinstance(widget, W.QCheckBox):
                widget.setChecked(str(value).upper() in ("1", "ON"))
            elif isinstance(widget, W.QComboBox):
                text = str(value).upper()
                aliases = {"NORM": "NORMAL", "ENV": "ENVELOPE", "AVER": "AVERAGE", "SING": "SINGLE", "NSIN": "NSINGLE", "ALEV": "ALEVEL", "EXT": "EXTERNAL"}
                text = aliases.get(text, text)
                index = widget.findData(text)
                if index < 0:
                    for i in range(widget.count()):
                        try:
                            if scalar(widget.itemData(i)) == scalar(text):
                                index = i
                                break
                        except ValueError:
                            pass
                if index < 0:
                    widget.addItem(str(value), text)
                    index = widget.count()-1
                widget.setCurrentIndex(index)
            else:
                widget.setText(str(value))
            self._confirmed[key] = self.widget_value(key)
            if preserve:
                if isinstance(widget, QuantityControl):
                    widget.editor.setText(current)
                    widget.editor.setModified(bool(modified))
                    widget._committed = committed
                elif isinstance(widget, W.QCheckBox):
                    widget.setChecked(current)
                else:
                    widget.setCurrentIndex(widget.findData(current))
        for key, default in (("level", "0"), ("slope", "RISE")):
            if key not in data:
                self._confirmed[key] = self._confirmed.get(key, default)
                if isinstance(self.fields[key], QuantityControl) and not self.fields[key].text():
                    self.fields[key].setText(default)
        self.loaded_channel = data["channel"]
        if self.loaded_channel == self.channel.currentData():
            self._refresh_requested = False
        self.loaded_host = self.host.text().strip()
        self._loaded = True
        self.running = data["running"]
        self._sampling.update({key: data[key] for key in ('tdiv', 'sample_rate', 'record_length') if key in data})
        self._channel_sampling[data['channel']] = {'vdiv': data.get('vdiv'),
            'unit': 'A' if str(data.get('probe', '')).upper().startswith('C') else 'V'}
        self.update_acquisition_info()
        self._updating = False
        self.update_run_button()
        self.update_enabled()
        self.trigger_type.setText(f"現在のタイプ: {data['trigger_type']}")
        self.status.setText(f"{data['identity']}\n{'RUN中' if data['running'] else '停止中'} · CH{data['channel']}の設定を読込")
