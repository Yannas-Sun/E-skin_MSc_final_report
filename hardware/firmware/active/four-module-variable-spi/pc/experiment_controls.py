"""Experiment metadata and schedule editor for the variable-SPI monitor."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import textwrap

import matplotlib.pyplot as plt
from matplotlib.widgets import Button, CheckButtons, RadioButtons, TextBox


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def local_provenance(firmware_dir: Path) -> dict:
    files = {
        'stm32_elf': firmware_dir / 'stm32/combined-system/build/Release/ESKIN_STM32.elf',
        'teensy_hex': firmware_dir / 'build/teensy/four_module.ino.hex',
        'pc_monitor': firmware_dir / 'pc/four-module-fsr-monitor.py',
        'pc_recorder': firmware_dir / 'pc/experiment_recording.py',
        'pc_plot_jobs': firmware_dir / 'pc/recording_plot_jobs.py',
        'pc_recording_plots': firmware_dir / 'pc/recording_plots.py',
        'pc_controls': Path(__file__),
        'pc_module_detection': firmware_dir / 'pc/module_detection.py',
    }
    return {'source': 'local_files_not_device_flash_readback',
            'firmware_variant': 'four-module-variable-spi',
            'files': {name: {'path': str(path), 'sha256': sha256_file(path)}
                      for name, path in files.items()}}


class ExperimentControls:
    """Human conditions; connection settings come from the monitor or schedule."""

    CONDITION_OPTIONS = (
        ('Zero load', 'zero_load'), ('Small area (3 x 1.6 cm)', 'small_area_3x1.6cm'),
        ('Large area', 'large_area'), ('Rolling', 'rolling'),
        ('Standard dynamic', 'standard_dynamic_load'), ('Other (describe in Notes)', 'other'),
    )

    def __init__(self, firmware_dir: Path, output_dir: Path, schedule_path: Path,
                 on_change=None, on_open=None, on_close=None) -> None:
        self.firmware_dir, self.output_dir, self.schedule_path = map(Path, (firmware_dir, output_dir, schedule_path))
        self.on_change, self.on_open, self.on_close = on_change, on_open, on_close
        self.rows: list[dict] = []
        self.row_index = 0
        self.duration_seconds, self.settle_seconds = 40.0, 10.0
        self.metadata = {
            'target_modules': [], 'module_selection_source': 'automatic', 'target_mode': 'FULL',
            'target_hz': 200, 'delta_threshold': 8, 'spi_setting_hz': 10000000,
            'condition': 'zero_load', 'block': '1', 'repeat': '1',
            'operator': '', 'load_protocol_id': '', 'load_layers': 'unspecified',
            'load_notes': '', 'notes': '', 'deployment_note': '', 'deployment_confirmed': False,
            'board_identity_handling': 'slots_only', 'physical_modules_to_slots': {},
            'board_identity_source': 'unknown_not_transmitted_by_protocol',
        }
        self.figure = None
        self.boxes: dict[str, TextBox] = {}
        self.radios: dict[str, RadioButtons] = {}
        self.buttons: list[Button] = []
        self.status = None
        self.last_error = ''
        self._auto_summary = ''
        self._auto_text = None
        self._settings_active = False
        self._close_connection = None
        self._radio_values = {}
        if self.schedule_path.is_file():
            self.load_schedule(self.schedule_path)

    @property
    def is_open(self) -> bool:
        exists = self.figure is not None and plt.fignum_exists(self.figure.number)
        if self._settings_active and not exists:
            self._finish_settings(close_figure=False)
        return bool(self._settings_active and exists)

    @property
    def auto_summary(self) -> str:
        return self._auto_summary

    @auto_summary.setter
    def auto_summary(self, value: str) -> None:
        self._auto_summary = str(value)
        if self._auto_text is not None and self.is_open:
            self._auto_text.set_text(self._automatic_description())
            self.figure.canvas.draw_idle()

    def _automatic_description(self) -> str:
        if self._auto_summary:
            return '\n'.join(textwrap.wrap(' '.join(self._auto_summary.split()), width=122)[:2])
        m = self.metadata
        slots = '+'.join(f'M{i}' for i in m['target_modules']) or 'waiting for valid frames'
        label = 'Plan expects' if m.get('module_selection_source') == 'schedule' else 'Auto slots'
        return f"{label}: {slots} | {m['target_mode']} | {m['target_hz']} Hz | SPI 10 MHz | threshold 8"

    def load_schedule(self, path: Path) -> None:
        path = Path(path)
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        if not rows:
            raise ValueError('Schedule is empty')
        required = {'modules', 'mode', 'condition', 'record_seconds', 'excluded_prefix_seconds'}
        if not required.issubset(rows[0]):
            raise ValueError('Schedule requires modules/mode/condition/record_seconds/excluded_prefix_seconds')
        self.rows, self.schedule_path, self.row_index = rows, path, 0

    @staticmethod
    def parse_modules(text: str) -> list[int]:
        parts = text.upper().replace('M', '').replace('+', ',').split(',')
        modules = [int(value.strip()) for value in parts if value.strip()]
        if not modules or len(set(modules)) != len(modules) or any(m not in range(4) for m in modules):
            raise ValueError('Modules must be unique slot numbers 0..3')
        return sorted(modules)

    def select_row(self, one_based: int) -> dict:
        if not 1 <= one_based <= len(self.rows):
            raise ValueError(f'Plan row must be 1..{len(self.rows)}')
        row = self.rows[one_based-1]
        modules, mode = self.parse_modules(row['modules']), row['mode'].upper()
        duration, settle = float(row['record_seconds']), float(row['excluded_prefix_seconds'])
        if mode not in ('FULL', 'DELTA') or not 0 <= settle < duration <= 86400:
            raise ValueError('Invalid mode or duration in schedule')
        previous = json.loads(json.dumps(self.metadata))
        old_duration, old_settle, old_index = self.duration_seconds, self.settle_seconds, self.row_index
        try:
            self.metadata.update({
                'target_modules': modules, 'module_selection_source': 'schedule', 'target_mode': mode,
                'target_hz': int(row.get('target_hz') or 200),
                'delta_threshold': int(row.get('delta_threshold') or 8),
                'spi_setting_hz': int(row.get('spi_hz') or 10000000),
                'condition': row['condition'], 'block': str(row.get('block') or '1'),
                'repeat': '1',
                'planned_repeat': str(row.get('repeat') or row.get('block') or '1'),
                'planned_id': row.get('planned_id', ''), 'pair_id': row.get('pair_id', ''),
                'group': row.get('group', ''), 'load_protocol_id': row.get('load_protocol_id', ''),
                'plan_notes': row.get('notes', ''), 'schedule_path': str(self.schedule_path),
                'schedule_row': one_based, 'schedule_record_seconds': duration,
                'schedule_settle_seconds': settle, 'schedule_duration_overridden': False,
            })
            self.duration_seconds, self.settle_seconds, self.row_index = duration, settle, one_based-1
            self.validate()
        except Exception:
            self.metadata = previous
            self.duration_seconds, self.settle_seconds, self.row_index = old_duration, old_settle, old_index
            raise
        # An open editor must not later overwrite a newly selected plan with stale controls.
        self.close_settings()
        self.last_error = ''
        if self.on_change:
            self.on_change()
        return row

    def validate(self) -> None:
        modules = self.metadata.get('target_modules', [])
        if not isinstance(modules, (list, tuple)):
            raise ValueError('Detected modules must be a list of slot numbers')
        if modules:
            self.parse_modules(','.join(map(str, modules)))
        if self.metadata['target_mode'] not in ('FULL', 'DELTA'):
            raise ValueError('Target mode must be FULL or DELTA')
        if not str(self.metadata['condition']).strip():
            raise ValueError('Condition is required')
        if not 0 <= float(self.settle_seconds) < float(self.duration_seconds) <= 86400:
            raise ValueError('Require 0 <= prefix seconds < record seconds <= 86400')
        if not 0 <= int(self.metadata['target_hz']) <= 1000:
            raise ValueError('Target Hz must be 0..1000')
        if int(self.metadata['delta_threshold']) != 8 or int(self.metadata['spi_setting_hz']) != 10000000:
            raise ValueError('This firmware configuration uses threshold 8 and SPI 10 MHz')

    def make_config(self):
        from experiment_recording import RecordingConfig
        self.validate()
        if not self.metadata.get('target_modules'):
            raise ValueError('No communicating module slots detected yet; wait for valid frames before recording')
        metadata = json.loads(json.dumps(self.metadata))
        metadata['N'], metadata['M'] = len(metadata['target_modules']), 4
        metadata['local_provenance'] = local_provenance(self.firmware_dir)
        return RecordingConfig(output_dir=self.output_dir, duration_seconds=float(self.duration_seconds),
                               settle_seconds=float(self.settle_seconds), metadata=metadata)

    def description(self) -> str:
        m = self.metadata
        # The main monitor reserves two lines; avoid carrying settings-window wrapping into it.
        automatic = ' '.join(self._automatic_description().splitlines())
        details = (f"{m.get('planned_id') or 'Manual'} | {m['condition']} | "
                   f"block {m['block']} | 3 x {self.duration_seconds:g}s = {3*self.duration_seconds:g}s "
                   f"(settle {self.settle_seconds:g}s each)")
        if self.last_error:
            details = 'Settings not saved: '+self.last_error
        return automatic+'\n'+details

    def _radio(self, key, title, bounds, options, current):
        options = list(options)
        if str(current) not in [str(value) for _, value in options]:
            options.append((f'Current: {current}', current))
        axis = self.figure.add_axes(bounds, facecolor='#f7f9fc')
        axis.set_title(title, loc='left', fontsize=10, fontweight='medium', pad=9)
        for spine in axis.spines.values():
            spine.set_edgecolor('#dce2ea')
        labels = [label for label, _ in options]
        active = next(i for i, (_, value) in enumerate(options) if str(value) == str(current))
        widget = RadioButtons(axis, labels, active=active, activecolor='#236d9c')
        for label in widget.labels:
            label.set_fontsize(9)
        self.radios[key] = widget
        self._radio_values[key] = dict(options)

    def show(self, _event=None) -> None:
        if self.is_open:
            self.figure.show()
            self.figure.canvas.draw_idle()
            return
        self.last_error = ''
        self._settings_active = True
        try:
            if self.on_open:
                self.on_open()
            self.figure = plt.figure(figsize=(11.2, 7.3), facecolor='white')
            self._close_connection = self.figure.canvas.mpl_connect('close_event', self._on_window_close)
            self.figure.suptitle('Experiment settings', fontsize=14, y=.975)
            self._auto_text = self.figure.text(.04, .925, self._automatic_description(),
                fontsize=9, color='#44546a', va='top')
            self.radios, self._radio_values, self.boxes = {}, {}, {}
            m = self.metadata
            self._radio('condition', 'Condition', [.04, .49, .32, .33], self.CONDITION_OPTIONS, m['condition'])
            self._radio('block', 'Block', [.40, .60, .13, .22], [(str(i), str(i)) for i in range(1, 4)], str(m['block']))
            self.figure.text(.59, .78, 'Repeat: automatic\n1 -> 2 -> 3',
                             fontsize=9, color='#44546a', va='top')
            self.figure.text(.59, .68, 'Same block.\nSeparate files.', fontsize=8, color='#526174', va='top')
            self._radio('duration', 'Duration (per recording)', [.78, .60, .18, .22],
                        [('40 s', '40'), ('310 s', '310')], f'{self.duration_seconds:g}')
            self.figure.text(.78, .552, 'Each includes 10 s settling.\nEach raw prefix is retained.', fontsize=8, color='#526174')
            self._radio('load_layers', 'Layers loaded', [.04, .245, .32, .18],
                        [('Unspecified', 'unspecified'), ('FSR1', 'FSR1'), ('FSR2', 'FSR2'), ('Both', 'both')],
                        m.get('load_layers', 'unspecified'))
            self._radio('board_identity_handling', 'Board identity', [.40, .245, .56, .18],
                        [('Slot positions only (board identity unknown)', 'slots_only'),
                         ('Fixed board labels (operator convention in Notes)', 'fixed_board_labels'),
                         ('Identity details in Notes', 'see_notes')], m.get('board_identity_handling', 'slots_only'))
            self.figure.text(.04, .206, 'M0-M3 name connection slots. The protocol does not transmit unique board IDs.',
                             fontsize=8, color='#526174')
            self.boxes['notes'] = TextBox(self.figure.add_axes([.105, .129, .855, .047]), 'Notes: ',
                                          initial=str(m.get('notes', '')))
            self.boxes['notes'].label.set_fontsize(9)
            self.boxes['notes'].text_disp.set_fontsize(9)
            self.status = self.figure.text(.04, .094,
                'Optional notes: force / area, placement, loading rhythm, or your board-to-slot labels.',
                fontsize=8, color='#526174')
            self.deployment_box = CheckButtons(self.figure.add_axes([.04, .026, .59, .043]),
                ['I confirm matching STM32 / Teensy builds were flashed (optional)'],
                [bool(m.get('deployment_confirmed', False))])
            self.deployment_box.labels[0].set_fontsize(8)
            save = Button(self.figure.add_axes([.71, .027, .13, .043]), 'Save & close')
            save.on_clicked(self._save)
            cancel = Button(self.figure.add_axes([.86, .027, .10, .043]), 'Cancel')
            cancel.on_clicked(lambda _event: self.close_settings())
            self.buttons = [save, cancel]
            self.figure.show()
        except Exception:
            self.close_settings()
            raise

    def _on_window_close(self, event):
        if self.figure is not None and event.canvas.figure is self.figure:
            self._finish_settings(close_figure=False)

    def _finish_settings(self, close_figure):
        figure, notify = self.figure, self._settings_active
        self.figure, self._settings_active, self._auto_text = None, False, None
        if figure is not None and self._close_connection is not None:
            figure.canvas.mpl_disconnect(self._close_connection)
        self._close_connection = None
        try:
            if close_figure and figure is not None:
                plt.close(figure)
        finally:
            if notify and self.on_close:
                self.on_close()

    def close_settings(self) -> None:
        """Close once and always release the monitor's settings pause, including under Agg."""
        self._finish_settings(close_figure=True)

    def _detach_schedule(self):
        for key in list(self.metadata):
            if key in ('planned_id', 'pair_id', 'group', 'plan_notes', 'schedule', 'N') or key.startswith(('schedule_', 'planned_')):
                self.metadata.pop(key, None)
        self.metadata['load_protocol_id'] = ''
        self.metadata['module_selection_source'] = 'automatic'
        self.metadata['target_modules'] = []
        self.metadata['repeat'] = '1'

    def _save(self, _event=None) -> None:
        if not self.is_open:
            return
        original = json.loads(json.dumps(self.metadata))
        old_duration, old_settle = self.duration_seconds, self.settle_seconds
        try:
            values = {key: self._radio_values[key][widget.value_selected] for key, widget in self.radios.items()}
            identity_changed = any(str(values[key]) != str(original.get(key, '')) for key in ('condition', 'block'))
            if identity_changed:
                self._detach_schedule()
            for key in ('condition', 'block', 'load_layers', 'board_identity_handling'):
                self.metadata[key] = str(values[key])
            self.metadata['notes'] = self.boxes['notes'].text.strip()
            handling = self.metadata['board_identity_handling']
            self.metadata['board_identity_source'] = ('unknown_not_transmitted_by_protocol' if handling == 'slots_only'
                                                     else 'operator_notes_not_device_uid')
            # Notes are optional plain text; do not manufacture a mapping from slot numbers.
            self.metadata['physical_modules_to_slots'] = {}
            self.metadata['deployment_confirmed'] = bool(self.deployment_box.get_status()[0])
            self.duration_seconds = float(values['duration'])
            self.settle_seconds = 10.0 if self.duration_seconds > 10 else old_settle
            if self.metadata.get('module_selection_source') == 'schedule':
                self.metadata['schedule_duration_overridden'] = (
                    self.duration_seconds != self.metadata.get('schedule_record_seconds', old_duration)
                    or self.settle_seconds != self.metadata.get('schedule_settle_seconds', old_settle))
            self.validate()
            if self.on_change:
                self.on_change()
            self.last_error = ''
        except Exception as exc:
            self.metadata = original
            self.duration_seconds, self.settle_seconds = old_duration, old_settle
            self.last_error = str(exc)
        finally:
            # A failed Save must not leave the main plot paused behind the editor.
            self.close_settings()
