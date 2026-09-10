"""Draw lifecycle: winner selection, multi-roll transitions, history, and MP4."""
from __future__ import annotations

import math
import queue
import random
import secrets
import threading
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import numpy as np
from PIL import Image

from ocr_import import recognize_reward_name

from .models import (
    DrawResult,
    NicknameCorrection,
    Participant,
    RecordedWheelFrame,
    clean_nickname,
    nickname_lookup_key,
    sort_participants_by_bm,
)
from .probabilities import (
    participant_probabilities,
    participant_weights,
    weighted_random_index,
)
from .theme import (
    ACCENT,
    ACCENT_DARK,
    APP_NAME,
    BACKGROUND,
    CTA_BACKGROUND,
    CTA_BORDER,
    CTA_DISABLED,
)
from .video import encode_mp4_frames


class DrawWorkflowMixin:
    @property
    def active_participants(self) -> list[Participant]:
        return [participant for participant in self.participants if participant.enabled]

    def _clear_winner_result(self) -> None:
        self.result_var.set("")
        self.result_sort_button.place_forget()
        if self.result_card.winfo_manager():
            self.result_card.pack_forget()
        self.result_slot.configure(bg=BACKGROUND)

    def _sort_winner_result_by_bm(self) -> None:
        if len(self._roll_winners) < 2:
            return
        participants = self._roll_slots or self.participants
        bm_by_name = {
            participant.name: participant.bm for participant in participants
        }
        sorted_winners = sorted(
            self._roll_winners,
            key=lambda name: bm_by_name.get(name, float("-inf")),
            reverse=True,
        )
        self._show_winner_result(" | ".join(sorted_winners))

    def _show_winner_result(self, winner: str) -> None:
        if len(winner) <= 24:
            font_size = 18
        elif len(winner) <= 55:
            font_size = 15
        elif len(winner) <= 90:
            font_size = 12
        else:
            font_size = 10
        self.result_var.set(winner)
        self.result_caption.configure(
            text="ПОБЕДИТЕЛИ" if " | " in winner else "ПОБЕДИТЕЛЬ"
        )
        self.result_label.configure(
            font=("Segoe UI Semibold", font_size),
            wraplength=self._px(740),
        )
        if " | " in winner:
            self.result_sort_button.place(
                relx=1.0,
                x=-self._px(6),
                y=self._px(4),
                anchor="ne",
                width=self._px(27),
                height=self._px(27),
            )
            self.result_sort_button.lift()
        else:
            self.result_sort_button.place_forget()
        self.result_slot.configure(bg=ACCENT_DARK)
        if not self.result_card.winfo_manager():
            self.result_card.pack(fill="both", expand=True, padx=1, pady=1)

    def _show_spin_controls(self) -> None:
        if self.result_actions.winfo_manager():
            self.result_actions.pack_forget()
        if not self.spin_button.winfo_manager():
            self.spin_button.pack(fill="x")

    def _show_result_controls(self) -> None:
        if self.spin_button.winfo_manager():
            self.spin_button.pack_forget()
        if not self.result_actions.winfo_manager():
            self.result_actions.pack(fill="x")

    def _set_video_ready(self, ready: bool) -> None:
        if not ready:
            self._video_preparation_failed = False
        self._refresh_result_preparation_state()

    def _refresh_result_preparation_state(self) -> None:
        if self._video_preparation_failed:
            self.button_process_text.stop()
            self.save_result_button.configure(
                state="disabled",
                text="MP4 НЕ СОЗДАН",
                bg=CTA_DISABLED,
                highlightbackground=CTA_DISABLED,
                highlightcolor=CTA_DISABLED,
            )
            return

        if self._roll_video_bytes is None or self._reward_ocr_pending:
            self.save_result_button.configure(
                state="disabled",
                bg=CTA_DISABLED,
                highlightbackground=CTA_DISABLED,
                highlightcolor=CTA_DISABLED,
            )
            process_name = (
                "ПОДГОТОВКА MP4"
                if self._roll_video_bytes is None
                else "РАСПОЗНАВАНИЕ НАГРАДЫ"
            )
            self.button_process_text.start(
                self.save_result_button,
                process_name,
            )
            return

        self.button_process_text.stop()
        self.save_result_button.configure(
            state="normal",
            text="СОХРАНИТЬ РЕЗУЛЬТАТ",
            bg=ACCENT,
            highlightbackground=ACCENT_DARK,
            highlightcolor=ACCENT_DARK,
        )

    def _begin_reward_recognition(self, winners: list[str]) -> None:
        generation = self._reward_ocr_generation
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        self._pending_draw_results = [
            DrawResult(winner, "", timestamp) for winner in winners
        ]
        self._roll_logged = False

        if self._roll_prize_image is None:
            self._pending_draw_results = [
                DrawResult(winner, "Награда не указана", timestamp)
                for winner in winners
            ]
            self._reward_ocr_pending = False
            self._refresh_result_preparation_state()
            return

        prize_image = self._roll_prize_image.copy()
        self._reward_ocr_pending = True
        self._reward_ocr_jobs += 1
        self._refresh_result_preparation_state()

        def worker() -> None:
            try:
                result: str | Exception = recognize_reward_name(prize_image)
            except Exception as error:
                result = error
            self._reward_ocr_queue.put((generation, result))

        threading.Thread(target=worker, daemon=True).start()
        if not self._reward_ocr_polling:
            self._reward_ocr_polling = True
            self.after(100, self._poll_reward_recognition)

    def _poll_reward_recognition(self) -> None:
        while True:
            try:
                generation, result = self._reward_ocr_queue.get_nowait()
            except queue.Empty:
                break
            self._reward_ocr_jobs = max(0, self._reward_ocr_jobs - 1)
            if generation != self._reward_ocr_generation:
                continue
            pending = self._pending_draw_results
            if not pending:
                continue
            reward = (
                result.strip()
                if isinstance(result, str) and result.strip()
                else "Награда не распознана"
            )
            self._pending_draw_results = [
                DrawResult(item.winner, reward, item.timestamp)
                for item in pending
            ]
            self._reward_ocr_pending = False
            self._refresh_result_preparation_state()

        if self._reward_ocr_jobs:
            self.after(100, self._poll_reward_recognition)
        else:
            self._reward_ocr_polling = False

    def _commit_pending_draw_result(self) -> None:
        if self._roll_logged or not self._pending_draw_results:
            return
        try:
            self.draw_log_store.append_many(self._pending_draw_results)
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror(
                APP_NAME,
                f"MP4 сохранён, но не удалось записать журнал:\n{error}",
                parent=self,
            )
            return
        self._roll_logged = True
        self.participants_panel.refresh_history_dialog()

    def _encode_roll_video(
        self,
        recorded_frames: list[RecordedWheelFrame],
        winners_caption: str,
        prize_image: Image.Image | None,
        prize_quantity: int,
        count_caption: str,
        background: Image.Image,
        overlay: Image.Image,
        generation: int | None = None,
    ) -> bytes:
        if not recorded_frames:
            raise ValueError("Нет кадров розыгрыша для записи")
        scene_base = self._build_video_scene_base(
            count_caption,
            prize_image,
            prize_quantity,
        )
        cached_probability_key: tuple[float, ...] | None = None
        cached_disc_array: np.ndarray | None = None

        def render_scene(
            state: RecordedWheelFrame,
            final: bool = False,
        ) -> Image.Image:
            nonlocal cached_probability_key, cached_disc_array
            probability_key = tuple(
                round(value, 8) for value in state.probabilities
            )
            if (
                cached_disc_array is None
                or probability_key != cached_probability_key
            ):
                cached_disc_array = np.asarray(
                    self._build_wheel_disc(list(state.probabilities))
                )
                cached_probability_key = probability_key
            wheel = self._render_recorded_wheel(
                background,
                cached_disc_array,
                overlay,
                state.rotation,
                list(state.names),
                list(state.probabilities),
                state.winner_index,
            )
            scene = scene_base.copy()
            scene.paste(
                wheel.crop((0, 0, self.CANVAS_SIZE, self.CANVAS_HEIGHT)),
                ((self.LEFT_PANEL_WIDTH - self.CANVAS_SIZE) // 2, 96),
            )
            if final:
                self._draw_recorded_winner_card(scene, winners_caption)
            return scene

        def frames() -> Iterable[Image.Image]:
            for state in recorded_frames:
                if (
                    generation is not None
                    and generation != self._video_generation
                ):
                    raise RuntimeError("MP4 generation cancelled")
                yield render_scene(state)

            final_scene = render_scene(recorded_frames[-1], final=True)
            final_frame_count = max(
                1,
                round(self.VIDEO_FINAL_HOLD_SECONDS * self.VIDEO_FPS),
            )
            for _index in range(final_frame_count):
                if (
                    generation is not None
                    and generation != self._video_generation
                ):
                    raise RuntimeError("MP4 generation cancelled")
                yield final_scene

        return encode_mp4_frames(
            frames(),
            (self.LEFT_PANEL_WIDTH, self.VIDEO_CAPTURE_HEIGHT),
            self.VIDEO_FPS,
        )

    def _begin_video_generation(
        self,
        winners: list[str],
    ) -> None:
        recorded_frames = list(self._video_frames)
        generation = self._video_generation
        prize_image = (
            self._roll_prize_image.copy()
            if self._roll_prize_image is not None
            else None
        )
        prize_quantity = self._roll_prize_quantity
        count_caption = str(self.count_label.cget("text"))
        background = self._wheel_background.copy()
        overlay = self._wheel_overlay.copy()
        winners_caption = " | ".join(winners)
        self._video_jobs += 1

        def worker() -> None:
            try:
                result: bytes | Exception = self._encode_roll_video(
                    recorded_frames,
                    winners_caption,
                    prize_image,
                    prize_quantity,
                    count_caption,
                    background,
                    overlay,
                    generation,
                )
            except Exception as error:
                result = error
            self._video_queue.put((generation, result))

        threading.Thread(target=worker, daemon=True).start()
        if not self._video_polling:
            self._video_polling = True
            self.after(100, self._poll_video_generation)

    def _poll_video_generation(self) -> None:
        while True:
            try:
                generation, result = self._video_queue.get_nowait()
            except queue.Empty:
                break
            self._video_jobs = max(0, self._video_jobs - 1)
            if generation != self._video_generation:
                continue
            if isinstance(result, bytes):
                self._roll_video_bytes = result
                self._set_video_ready(True)
            else:
                self._roll_video_bytes = None
                self._video_preparation_failed = True
                self._refresh_result_preparation_state()
                messagebox.showerror(
                    APP_NAME,
                    f"Не удалось подготовить MP4:\n{result}",
                    parent=self,
                )

        if self._video_jobs:
            self.after(100, self._poll_video_generation)
        else:
            self._video_polling = False

    def _save_roll_video(self) -> None:
        if self._roll_video_bytes is None:
            return
        initial_name = datetime.now().strftime(
            "Розыгрыш_%Y-%m-%d_%H-%M-%S.mp4"
        )
        destination = filedialog.asksaveasfilename(
            parent=self,
            title="Сохранить результат розыгрыша",
            initialfile=initial_name,
            defaultextension=".mp4",
            filetypes=(("MP4", "*.mp4"),),
        )
        if not destination:
            return
        try:
            Path(destination).write_bytes(self._roll_video_bytes)
        except OSError as error:
            messagebox.showerror(
                APP_NAME,
                f"Не удалось сохранить MP4:\n{error}",
                parent=self,
            )
            return
        self._commit_pending_draw_result()

    def _cancel_roll_result(self) -> None:
        if self.spinning:
            return
        self.button_process_text.stop()
        self._video_generation += 1
        self._reward_ocr_generation += 1
        self._roll_video_bytes = None
        self._video_frames.clear()
        self._roll_prize_image = None
        self._video_preparation_failed = False
        self._reward_ocr_pending = False
        self._pending_draw_results = []
        self._roll_logged = False
        self._winner_index = None
        self._show_winner_glow = False
        self._roll_slots = None
        self._roll_remaining = []
        self._roll_probabilities = None
        self._roll_winners = []
        self._roll_target_count = 1
        self.rotation = 0.0
        self._clear_winner_result()
        self._show_spin_controls()
        self.prize_card.set_locked(False)
        self.prize_quantity_control.set_locked(False)
        self._draw_wheel()

    def set_participants(
        self, participants: list[Participant], bm_influence_percent: float
    ) -> None:
        self.button_process_text.stop()
        participants = sort_participants_by_bm(participants)
        self.store.save(participants, bm_influence_percent)
        self.participants = participants
        self.bm_influence_percent = bm_influence_percent
        self.rotation = 0.0
        self._winner_index = None
        self._video_generation += 1
        self._reward_ocr_generation += 1
        self._roll_video_bytes = None
        self._video_frames.clear()
        self._roll_prize_image = None
        self._video_preparation_failed = False
        self._reward_ocr_pending = False
        self._pending_draw_results = []
        self._roll_logged = False
        self._show_winner_glow = False
        self._roll_slots = None
        self._roll_remaining = []
        self._roll_probabilities = None
        self._roll_winners = []
        self._roll_target_count = 1
        self._clear_winner_result()
        self._show_spin_controls()
        self.prize_card.set_locked(False)
        self.prize_quantity_control.set_locked(False)
        self._update_count()
        self._request_wheel_redraw()

    def corrected_nickname(self, recognized_name: str) -> str:
        key = nickname_lookup_key(recognized_name)
        for correction in self.nickname_corrections:
            if nickname_lookup_key(correction.recognized) == key:
                return correction.replacement
        return clean_nickname(recognized_name)

    def remember_nickname_corrections(
        self, updates: list[tuple[str, str]]
    ) -> None:
        corrections = {
            nickname_lookup_key(correction.recognized): correction
            for correction in self.nickname_corrections
        }
        for recognized_name, replacement_name in updates:
            recognized = clean_nickname(recognized_name)
            replacement = clean_nickname(replacement_name)
            key = nickname_lookup_key(recognized)
            if not key or not replacement:
                continue
            if recognized == replacement:
                corrections.pop(key, None)
            else:
                corrections[key] = NicknameCorrection(recognized, replacement)
        updated = list(corrections.values())
        self.store.save(
            self.participants,
            self.bm_influence_percent,
            updated,
        )
        self.nickname_corrections = updated

    def remove_nickname_correction(self, recognized_name: str) -> None:
        key = nickname_lookup_key(recognized_name)
        updated = [
            correction
            for correction in self.nickname_corrections
            if nickname_lookup_key(correction.recognized) != key
        ]
        if len(updated) == len(self.nickname_corrections):
            return
        self.store.save(
            self.participants,
            self.bm_influence_percent,
            updated,
        )
        self.nickname_corrections = updated

    def _update_count(self) -> None:
        active = len(self.active_participants)
        total = len(self.participants)
        if active == total:
            caption = f"Участвуют: {active}"
        else:
            caption = f"Участвуют: {active} из {total}"
        self.count_label.configure(text=caption)

    def _start_spin(self) -> None:
        if self.spinning:
            return
        self.participants_panel.flush_auto_save()
        active = self.active_participants
        if len(active) < 2:
            messagebox.showwarning(
                APP_NAME,
                "Для вращения выберите хотя бы двух участников.",
                parent=self,
            )
            return

        winner_count = self.prize_quantity_control.value()
        if winner_count > len(active):
            messagebox.showwarning(
                APP_NAME,
                "Количество наград не может превышать число выбранных "
                "участников.",
                parent=self,
            )
            return

        self.spinning = True
        self._winner_index = None
        self._show_winner_glow = False
        self._video_generation += 1
        self._reward_ocr_generation += 1
        self._roll_video_bytes = None
        self._video_preparation_failed = False
        self._reward_ocr_pending = False
        self._pending_draw_results = []
        self._roll_logged = False
        self._roll_prize_image = (
            self.prize_card.image.copy()
            if self.prize_card.image is not None
            else None
        )
        self._roll_prize_quantity = winner_count
        self._roll_target_count = winner_count
        self._roll_slots = list(active)
        self._roll_remaining = list(active)
        self._roll_winners = []
        self._roll_probabilities = self._mapped_roll_probabilities(active)
        self._video_frames = []
        self.prize_card.set_locked(True)
        self.prize_quantity_control.set_locked(True)
        self.spin_button.configure(
            state="disabled",
            bg=CTA_DISABLED,
            highlightbackground=CTA_DISABLED,
            highlightcolor=CTA_DISABLED,
        )
        self.button_process_text.start(
            self.spin_button, "КОЛЕСО ВРАЩАЕТСЯ"
        )
        self.participants_panel.set_editing_enabled(False)
        self._clear_winner_result()

        self._start_next_roll()

    def _mapped_roll_probabilities(
        self,
        pool: list[Participant],
    ) -> list[float]:
        if self._roll_slots is None:
            return []
        if not pool:
            return [0.0] * len(self._roll_slots)
        pool_probabilities = participant_probabilities(
            pool,
            self.bm_influence_percent,
            self.participants,
        )
        probability_by_identity = {
            id(participant): probability
            for participant, probability in zip(pool, pool_probabilities)
        }
        return [
            probability_by_identity.get(id(participant), 0.0)
            for participant in self._roll_slots
        ]

    def _start_next_roll(self) -> None:
        pool = list(self._roll_remaining)
        slots = self._roll_slots
        if slots is None or not pool:
            self._complete_roll()
            return

        probabilities = self._mapped_roll_probabilities(pool)
        self._roll_probabilities = probabilities
        self._winner_index = None
        self._show_winner_glow = False
        self._ensure_wheel_assets(probabilities)

        weights = participant_weights(
            pool,
            self.bm_influence_percent,
            self.participants,
        )
        pool_winner_index = weighted_random_index(weights)
        winner_participant = pool[pool_winner_index]
        winner_slot_index = next(
            index
            for index, participant in enumerate(slots)
            if participant is winner_participant
        )
        segment = probabilities[winner_slot_index] * 360.0
        winner_start = sum(probabilities[:winner_slot_index]) * 360.0
        jitter = random.uniform(-segment * 0.23, segment * 0.23)
        desired_rotation = 90.0 - (winner_start + segment / 2.0) + jitter
        delta_to_target = (desired_rotation - self.rotation) % 360.0
        multi_roll = self._roll_target_count > 1
        turns = (5 if multi_roll else 6) + secrets.randbelow(3)
        total_delta = turns * 360.0 + delta_to_target
        start_rotation = self.rotation
        duration = (
            self.MULTI_SPIN_DURATION_SECONDS
            if multi_roll
            else self.SPIN_DURATION_SECONDS
        )
        started_at = time.perf_counter()

        video_frame_count = max(1, math.ceil(duration * self.VIDEO_FPS))
        slot_names = tuple(participant.name for participant in slots)
        probability_tuple = tuple(probabilities)
        for frame_index in range(video_frame_count + 1):
            progress = frame_index / video_frame_count
            eased = 0.5 - 0.5 * math.cos(math.pi * progress)
            frame_rotation = (start_rotation + total_delta * eased) % 360.0
            self._video_frames.append(
                RecordedWheelFrame(
                    frame_rotation,
                    slot_names,
                    probability_tuple,
                )
            )

        remaining = [
            participant
            for participant in pool
            if participant is not winner_participant
        ]
        end_probabilities = self._mapped_roll_probabilities(remaining)
        transition_steps = max(
            2,
            round(self.SECTOR_TRANSITION_SECONDS * self.VIDEO_FPS) + 1,
        )
        transition_probabilities: list[list[float]] = []
        for step in range(transition_steps):
            progress = step / (transition_steps - 1)
            eased = 0.5 - 0.5 * math.cos(math.pi * progress)
            transition_probabilities.append(
                [
                    start + (end - start) * eased
                    for start, end in zip(probabilities, end_probabilities)
                ]
            )

        transition_discs: queue.Queue[list[Image.Image] | Exception] = (
            queue.Queue(maxsize=1)
        )

        def prepare_transition() -> None:
            try:
                discs: list[Image.Image] | Exception = [
                    self._build_wheel_disc(values)
                    for values in transition_probabilities
                ]
            except Exception as error:
                discs = error
            transition_discs.put(discs)

        if multi_roll:
            threading.Thread(target=prepare_transition, daemon=True).start()

        def animate() -> None:
            frame_started = time.perf_counter()
            elapsed = time.perf_counter() - started_at
            progress = min(1.0, elapsed / duration)
            eased = 0.5 - 0.5 * math.cos(math.pi * progress)
            self.rotation = start_rotation + total_delta * eased
            self._draw_wheel()
            if progress < 1.0:
                render_ms = (time.perf_counter() - frame_started) * 1000.0
                delay_ms = max(1, round(1000.0 / 60.0 - render_ms))
                self.after(delay_ms, animate)
                return

            self.rotation %= 360.0
            self._round_stopped(
                winner_participant,
                winner_slot_index,
                probabilities,
                remaining,
                transition_probabilities,
                transition_discs,
            )

        animate()

    def _round_stopped(
        self,
        winner: Participant,
        winner_slot_index: int,
        probabilities: list[float],
        remaining: list[Participant],
        transition_probabilities: list[list[float]],
        transition_discs: queue.Queue[list[Image.Image] | Exception],
    ) -> None:
        slots = self._roll_slots
        if slots is None:
            return
        self._roll_winners.append(winner.name)
        self._winner_index = winner_slot_index
        self._show_winner_glow = True
        self._draw_wheel()

        names = tuple(participant.name for participant in slots)
        highlighted_state = RecordedWheelFrame(
            self.rotation,
            names,
            tuple(probabilities),
            winner_slot_index,
        )
        if self._roll_target_count > 1:
            hold_frames = max(
                1,
                round(self.MULTI_WINNER_HOLD_SECONDS * self.VIDEO_FPS),
            )
            self._video_frames.extend([highlighted_state] * hold_frames)
            self.after(
                round(self.MULTI_WINNER_HOLD_SECONDS * 1000),
                lambda: self._play_sector_transition(
                    remaining,
                    transition_probabilities,
                    transition_discs,
                ),
            )
            return

        self._video_frames.append(highlighted_state)
        self._complete_roll()

    def _play_sector_transition(
        self,
        remaining: list[Participant],
        transition_probabilities: list[list[float]],
        transition_discs: queue.Queue[list[Image.Image] | Exception],
    ) -> None:
        try:
            prepared = transition_discs.get_nowait()
        except queue.Empty:
            self.after(
                40,
                lambda: self._play_sector_transition(
                    remaining,
                    transition_probabilities,
                    transition_discs,
                ),
            )
            return

        if isinstance(prepared, Exception):
            prepared = [
                self._build_wheel_disc(values)
                for values in transition_probabilities
            ]

        slots = self._roll_slots
        if slots is None:
            return
        names = tuple(participant.name for participant in slots)
        self._show_winner_glow = False
        self._winner_index = None
        self._video_frames.extend(
            RecordedWheelFrame(
                self.rotation,
                names,
                tuple(values),
            )
            for values in transition_probabilities
        )
        interval_ms = max(
            1,
            round(
                self.SECTOR_TRANSITION_SECONDS
                * 1000
                / max(1, len(prepared) - 1)
            ),
        )

        def show_step(index: int) -> None:
            values = transition_probabilities[index]
            disc = prepared[index]
            self._roll_probabilities = list(values)
            self._wheel_disc = disc
            self._wheel_disc_array = np.asarray(disc)
            self._wheel_cache_key = tuple(round(value, 12) for value in values)
            self._draw_wheel()
            if index + 1 < len(prepared):
                self.after(interval_ms, lambda: show_step(index + 1))
                return

            self._roll_remaining = remaining
            if len(self._roll_winners) < self._roll_target_count:
                self.after(120, self._start_next_roll)
            else:
                self._complete_roll()

        show_step(0)

    def _complete_roll(self) -> None:
        winners = list(self._roll_winners)
        if not winners:
            return
        self.spinning = False
        self.button_process_text.stop()
        self.spin_button.configure(
            state="normal",
            text="КРУТИТЬ КОЛЕСО",
            bg=CTA_BACKGROUND,
            highlightbackground=CTA_BORDER,
            highlightcolor=CTA_BORDER,
        )
        self.participants_panel.set_editing_enabled(True)
        self.prize_card.set_locked(False)
        self.prize_quantity_control.set_locked(False)
        winners_caption = " | ".join(winners)
        self._show_winner_result(winners_caption)
        self._show_result_controls()
        self._set_video_ready(False)
        self._begin_reward_recognition(winners)
        self._begin_video_generation(winners)
