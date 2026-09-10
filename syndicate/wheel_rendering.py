"""Wheel drawing, antialiased assets, and recorded-result scene rendering."""
from __future__ import annotations

import math
import os
import queue
import threading
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageTk

from .platform import resource_path
from .probabilities import participant_probabilities
from .theme import (
    ACCENT,
    ACCENT_DARK,
    ACCENT_HOVER,
    APP_NAME,
    BACKGROUND,
    BORDER,
    BORDER_LIGHT,
    MUTED,
    SURFACE,
    TEXT,
    TEXT_BRIGHT,
    WHEEL_COLORS,
    WHEEL_METAL,
    WHEEL_METAL_DARK,
    WHEEL_METAL_LIGHT,
    WHEEL_METAL_SHADOW,
    WHEEL_SEPARATOR,
    WINNER_BACKGROUND,
    WINNER_SECTOR,
)
from .widgets import PrizeImageCard


class WheelRenderingMixin:
    def _draw_wheel(self) -> None:
        canvas = self.wheel_canvas
        if self._roll_slots is not None and self._roll_probabilities is not None:
            active = self._roll_slots
            probabilities = self._roll_probabilities
        else:
            active = self.active_participants
            probabilities = participant_probabilities(
                active, self.bm_influence_percent, self.participants
            )
        cx, cy, radius = self.CENTER_X, self.CENTER_Y, self.RADIUS

        self._ensure_wheel_assets(probabilities)
        image = self._wheel_background.copy()
        disc = self._wheel_disc
        if active and self.rotation % 360.0:
            if self._wheel_disc_array is None:
                self._wheel_disc_array = np.asarray(self._wheel_disc)
            disc_height, disc_width = self._wheel_disc_array.shape[:2]
            transform = cv2.getRotationMatrix2D(
                ((disc_width - 1) / 2.0, (disc_height - 1) / 2.0),
                self.rotation,
                1.0,
            )
            rotated = cv2.warpAffine(
                self._wheel_disc_array,
                transform,
                (disc_width, disc_height),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(0, 0, 0, 0),
            )
            disc = Image.fromarray(rotated)
        image.paste(disc, self._wheel_disc_offset, disc)
        if (
            self._show_winner_glow
            and self._winner_index is not None
            and 0 <= self._winner_index < len(probabilities)
        ):
            winner_glow = self._build_winner_glow(
                probabilities, self._winner_index
            )
            image.paste(winner_glow, (0, 0), winner_glow)
        image.paste(self._wheel_overlay, (0, 0), self._wheel_overlay)
        display_image = image
        if self.display_canvas_size != self.CANVAS_SIZE:
            display_image = image.resize(
                (self.display_canvas_size, self.display_canvas_size),
                Image.Resampling.LANCZOS,
            )
        if hasattr(self, "_wheel_image"):
            self._wheel_image.paste(display_image)
        else:
            self._wheel_image = ImageTk.PhotoImage(display_image)
            canvas.create_image(0, 0, image=self._wheel_image, anchor="nw")
        canvas.delete("labels")

        if not active:
            return

        angle_offset = 0.0
        for index, participant in enumerate(active):
            segment = probabilities[index] * 360.0
            if probabilities[index] <= 0.0001:
                angle_offset += segment
                continue
            start = self.rotation + angle_offset
            middle = math.radians(start + segment / 2.0)
            label_radius = radius * (
                self.LABEL_RADIUS_RATIO
                if len(active) <= 12
                else self.DENSE_LABEL_RADIUS_RATIO
            )
            x = (cx + label_radius * math.cos(middle)) * self.ui_scale
            y = (cy - label_radius * math.sin(middle)) * self.ui_scale
            label = participant.name
            limit = 13 if len(active) <= 10 else 9
            if len(label) > limit:
                label = label[: limit - 1] + "…"
            name_size = 10 if len(active) <= 20 else 9
            probability_size = 9 if len(active) <= 12 else 8
            probability_text = f"{probabilities[index] * 100:.2f}%"
            if not self.spinning:
                canvas.create_text(
                    x + self._px(1),
                    y - self._px(6),
                    text=label,
                    fill="#090A09",
                    font=("Segoe UI Semibold", name_size),
                    width=self._px(95),
                    justify="center",
                    tags="labels",
                )
                canvas.create_text(
                    x + self._px(1),
                    y + self._px(10),
                    text=probability_text,
                    fill="#090A09",
                    font=("Segoe UI", probability_size),
                    width=self._px(95),
                    justify="center",
                    tags="labels",
                )
            canvas.create_text(
                x,
                y - self._px(7),
                text=label,
                fill=TEXT_BRIGHT,
                font=("Segoe UI Semibold", name_size),
                width=self._px(95),
                justify="center",
                tags="labels",
            )
            canvas.create_text(
                x,
                y + self._px(9),
                text=probability_text,
                fill=TEXT_BRIGHT,
                font=("Segoe UI", probability_size),
                width=self._px(95),
                justify="center",
                tags="labels",
            )
            angle_offset += segment

    def _build_winner_glow(
        self,
        probabilities: list[float],
        winner_index: int,
        rotation: float | None = None,
    ) -> Image.Image:
        """Return an antialiased gold highlight for the winning sector."""

        scale = self.DISC_ANTIALIAS_SCALE
        width = self.CANVAS_SIZE * scale
        center_x = self.CENTER_X * scale
        center_y = self.CENTER_Y * scale
        radius = self.RADIUS * scale
        segment = probabilities[winner_index] * 360.0
        rotation_value = self.rotation if rotation is None else rotation
        start = rotation_value + sum(probabilities[:winner_index]) * 360.0
        steps = max(4, math.ceil(segment / 1.5))
        points = [(center_x, center_y)]
        for step in range(steps + 1):
            angle = math.radians(start + segment * step / steps)
            points.append(
                (
                    round(center_x + radius * math.cos(angle)),
                    round(center_y - radius * math.sin(angle)),
                )
            )

        gold = ImageColor.getrgb(ACCENT)
        light_gold = ImageColor.getrgb(ACCENT_HOVER)
        winner_color = ImageColor.getrgb(WINNER_SECTOR)
        glow_seed = Image.new("RGBA", (width, width), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_seed)
        glow_draw.line(
            points + [points[0]],
            fill=(*gold, 180),
            width=5 * scale,
            joint="curve",
        )
        glow = glow_seed.filter(ImageFilter.GaussianBlur(10 * scale))

        highlight = Image.new("RGBA", (width, width), (0, 0, 0, 0))
        highlight_draw = ImageDraw.Draw(highlight)
        highlight_draw.polygon(points, fill=(*winner_color, 255))
        highlight_draw.line(
            points + [points[0]],
            fill=(*light_gold, 210),
            width=2 * scale,
            joint="curve",
        )
        glow = Image.alpha_composite(glow, highlight)

        # Let the highlight run slightly under the opaque centre emblem so
        # antialiasing cannot leave a dark seam between the sector and medallion.
        annulus = Image.new("L", (width, width), 0)
        annulus_draw = ImageDraw.Draw(annulus)
        outer_radius = radius - 5 * scale
        inner_radius = (self.CENTER_MEDALLION_RADIUS - 2) * scale
        annulus_draw.ellipse(
            (
                center_x - outer_radius,
                center_y - outer_radius,
                center_x + outer_radius,
                center_y + outer_radius,
            ),
            fill=255,
        )
        annulus_draw.ellipse(
            (
                center_x - inner_radius,
                center_y - inner_radius,
                center_x + inner_radius,
                center_y + inner_radius,
            ),
            fill=0,
        )
        glow.putalpha(ImageChops.multiply(glow.getchannel("A"), annulus))
        return glow.resize(
            (self.CANVAS_SIZE, self.CANVAS_SIZE), Image.Resampling.LANCZOS
        )

    @staticmethod
    @lru_cache(maxsize=64)
    def _recording_font(
        size: int,
        bold: bool = False,
        text: str = "",
    ) -> ImageFont.ImageFont:
        has_japanese = any("\u3040" <= char <= "\u30ff" for char in text)
        has_hangul = any("\uac00" <= char <= "\ud7af" for char in text)
        has_cjk = any("\u3400" <= char <= "\u9fff" for char in text)

        if has_japanese:
            font_names = (
                "YuGothB.ttc" if bold else "YuGothM.ttc",
                "msgothic.ttc",
                "msyhbd.ttc" if bold else "msyh.ttc",
            )
        elif has_hangul:
            font_names = (
                "malgunbd.ttf" if bold else "malgun.ttf",
                "msyhbd.ttc" if bold else "msyh.ttc",
            )
        elif has_cjk:
            font_names = (
                "msyhbd.ttc" if bold else "msyh.ttc",
                "simsunb.ttf" if bold else "simsun.ttc",
                "YuGothB.ttc" if bold else "YuGothM.ttc",
            )
        else:
            font_names = ("seguisb.ttf" if bold else "segoeui.ttf",)

        windows_root = Path(os.environ.get("WINDIR", "C:\\Windows"))
        for font_name in font_names:
            candidates = (windows_root / "Fonts" / font_name, Path(font_name))
            for candidate in candidates:
                try:
                    return ImageFont.truetype(str(candidate), size=size)
                except OSError:
                    continue

        # Preserve the old Latin/Cyrillic fallback if an optional Windows CJK
        # font is unavailable on a particular installation.
        fallback_name = "seguisb.ttf" if bold else "segoeui.ttf"
        for candidate in (
            windows_root / "Fonts" / fallback_name,
            Path(fallback_name),
        ):
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except OSError:
                continue
        return ImageFont.load_default()

    def _render_recorded_wheel(
        self,
        background: Image.Image,
        disc_array: np.ndarray,
        overlay: Image.Image,
        rotation: float,
        names: list[str],
        probabilities: list[float],
        winner_index: int | None = None,
    ) -> Image.Image:
        image = background.copy()
        disc_height, disc_width = disc_array.shape[:2]
        transform = cv2.getRotationMatrix2D(
            ((disc_width - 1) / 2.0, (disc_height - 1) / 2.0),
            rotation,
            1.0,
        )
        rotated = cv2.warpAffine(
            disc_array,
            transform,
            (disc_width, disc_height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0),
        )
        disc = Image.fromarray(rotated)
        image.paste(disc, self._wheel_disc_offset, disc)
        if winner_index is not None:
            glow = self._build_winner_glow(
                probabilities,
                winner_index,
                rotation=rotation,
            )
            image.paste(glow, (0, 0), glow)
        image.paste(overlay, (0, 0), overlay)

        label_draw = ImageDraw.Draw(image)
        name_font_size = 14 if len(names) <= 20 else 13
        probability_font = self._recording_font(
            12 if len(names) <= 12 else 11
        )
        angle_offset = 0.0
        for index, name in enumerate(names):
            segment = probabilities[index] * 360.0
            if probabilities[index] <= 0.0001:
                angle_offset += segment
                continue
            middle = math.radians(rotation + angle_offset + segment / 2.0)
            label_radius = self.RADIUS * (
                self.LABEL_RADIUS_RATIO
                if len(names) <= 12
                else self.DENSE_LABEL_RADIUS_RATIO
            )
            x = self.CENTER_X + label_radius * math.cos(middle)
            y = self.CENTER_Y - label_radius * math.sin(middle)
            limit = 13 if len(names) <= 10 else 9
            visible_name = name if len(name) <= limit else name[: limit - 1] + "…"
            name_font = self._recording_font(
                name_font_size,
                bold=True,
                text=visible_name,
            )
            label_draw.text(
                (x, y - 7),
                visible_name,
                fill=TEXT_BRIGHT,
                font=name_font,
                anchor="mm",
                stroke_width=1,
                stroke_fill="#090A09",
            )
            label_draw.text(
                (x, y + 9),
                f"{probabilities[index] * 100:.2f}%",
                fill=TEXT_BRIGHT,
                font=probability_font,
                anchor="mm",
                stroke_width=1,
                stroke_fill="#090A09",
            )
            angle_offset += segment
        return image

    def _render_prize_snapshot(
        self, prize_image: Image.Image | None
    ) -> Image.Image:
        if prize_image is None:
            width = PrizeImageCard.EMPTY_WIDTH
            height = PrizeImageCard.EMPTY_HEIGHT
            card = Image.new("RGB", (width, height), SURFACE)
            card_draw = ImageDraw.Draw(card)
            card_draw.rectangle(
                (1, 1, width - 2, height - 2),
                outline=BORDER,
                width=2,
            )
            cx, cy = width // 2, height // 2
            card_draw.line(
                (cx - 13, cy, cx + 13, cy),
                fill=MUTED,
                width=3,
            )
            card_draw.line(
                (cx, cy - 13, cx, cy + 13),
                fill=MUTED,
                width=3,
            )
            return card

        source = prize_image.convert("RGBA")
        source.thumbnail(
            (PrizeImageCard.MAX_IMAGE_WIDTH, PrizeImageCard.MAX_IMAGE_HEIGHT),
            Image.Resampling.LANCZOS,
        )
        padding = PrizeImageCard.BORDER_PADDING
        card = Image.new(
            "RGBA",
            (source.width + padding * 2, source.height + padding * 2),
            ImageColor.getrgb(SURFACE) + (255,),
        )
        card.alpha_composite(source, (padding, padding))
        card_draw = ImageDraw.Draw(card)
        card_draw.rectangle(
            (1, 1, card.width - 2, card.height - 2),
            outline=BORDER_LIGHT,
            width=2,
        )
        return card.convert("RGB")

    def _build_video_scene_base(
        self,
        count_caption: str,
        prize_image: Image.Image | None,
        prize_quantity: int,
    ) -> Image.Image:
        scene = Image.new(
            "RGB",
            (self.LEFT_PANEL_WIDTH, self.VIDEO_CAPTURE_HEIGHT),
            BACKGROUND,
        )
        scene_draw = ImageDraw.Draw(scene)
        scene_draw.text(
            (26, 31),
            APP_NAME,
            fill=TEXT,
            font=self._recording_font(29, bold=True),
            anchor="lm",
        )
        scene_draw.text(
            (26, 72),
            count_caption,
            fill=MUTED,
            font=self._recording_font(12),
            anchor="lm",
        )
        prize = self._render_prize_snapshot(prize_image)
        prize_x = self.LEFT_PANEL_WIDTH - 22 - prize.width
        prize_y = 18 + (78 - prize.height) // 2
        scene.paste(prize, (prize_x, prize_y))
        if prize_quantity > 1:
            scene_draw.text(
                (prize_x - 12, 57),
                f"{int(prize_quantity)} X",
                fill=TEXT,
                font=self._recording_font(20, bold=True),
                anchor="rm",
            )
        return scene

    def _draw_recorded_winner_card(
        self, scene: Image.Image, winner: str
    ) -> None:
        card_box = (23, 840, self.LEFT_PANEL_WIDTH - 23, 902)
        scene_draw = ImageDraw.Draw(scene)
        scene_draw.rectangle(
            card_box,
            fill=WINNER_BACKGROUND,
            outline=ACCENT,
            width=2,
        )
        center_x = self.LEFT_PANEL_WIDTH // 2
        scene_draw.text(
            (center_x, 853),
            "ПОБЕДИТЕЛЬ",
            fill=MUTED,
            font=self._recording_font(12, bold=True),
            anchor="mm",
        )
        scene_draw.line(
            (center_x - 105, 865, center_x + 105, 865),
            fill=ACCENT,
            width=1,
        )
        if len(winner) <= 24:
            name_size = 25
        elif len(winner) <= 55:
            name_size = 20
        elif len(winner) <= 90:
            name_size = 16
        else:
            name_size = 13
        scene_draw.text(
            (center_x, 883),
            winner,
            fill=TEXT_BRIGHT,
            font=self._recording_font(name_size, bold=True, text=winner),
            anchor="mm",
        )

    def _request_wheel_redraw(self) -> None:
        active = self.active_participants
        probabilities = participant_probabilities(
            active, self.bm_influence_percent, self.participants
        )
        cache_key = tuple(round(value, 12) for value in probabilities)

        if self._wheel_cache_key == cache_key:
            self._wheel_render_generation += 1
            self._wheel_pending_key = None
            self._draw_wheel()
            return
        if self._wheel_pending_key == cache_key:
            return

        self._ensure_static_wheel_assets()
        self._wheel_render_generation += 1
        generation = self._wheel_render_generation
        self._wheel_pending_key = cache_key
        self._wheel_render_jobs += 1

        def worker() -> None:
            try:
                disc = self._build_wheel_disc(probabilities)
            except Exception:
                disc = None
            self._wheel_render_queue.put((generation, cache_key, disc))

        threading.Thread(target=worker, daemon=True).start()
        if not self._wheel_render_polling:
            self._wheel_render_polling = True
            self.after(10, self._poll_wheel_render)

    def _poll_wheel_render(self) -> None:
        newest_ready = False
        while True:
            try:
                generation, cache_key, disc = self._wheel_render_queue.get_nowait()
            except queue.Empty:
                break
            self._wheel_render_jobs = max(0, self._wheel_render_jobs - 1)
            if generation != self._wheel_render_generation:
                continue
            self._wheel_pending_key = None
            if disc is not None:
                self._wheel_disc = disc
                self._wheel_disc_array = np.asarray(disc)
                self._wheel_cache_key = cache_key
                newest_ready = True

        if newest_ready and not self.spinning:
            self._draw_wheel()

        if self._wheel_render_jobs:
            self.after(10, self._poll_wheel_render)
        else:
            self._wheel_render_polling = False

    def _ensure_wheel_assets(self, probabilities: list[float]) -> None:
        """Build only the sector layer when participant probabilities change."""
        self._ensure_static_wheel_assets()
        cache_key = tuple(round(value, 12) for value in probabilities)
        if self._wheel_cache_key == cache_key:
            return

        self._wheel_disc = self._build_wheel_disc(probabilities)
        self._wheel_disc_array = np.asarray(self._wheel_disc)
        self._wheel_cache_key = cache_key

    def _build_wheel_disc(self, probabilities: list[float]) -> Image.Image:
        """Render the mutable sector disc without accessing Tk."""

        active_count = len(probabilities) if sum(probabilities) > 1e-12 else 0

        scale = self.DISC_ANTIALIAS_SCALE
        radius = self.RADIUS

        def scaled(values: tuple[float, ...]) -> tuple[int, ...]:
            return tuple(round(value * scale) for value in values)

        disc_margin = 6
        disc_size = (radius + disc_margin) * 2
        high_disc_size = (disc_size * scale, disc_size * scale)
        disc_center = radius + disc_margin
        disc_box = (
            disc_margin,
            disc_margin,
            disc_margin + radius * 2,
            disc_margin + radius * 2,
        )
        if active_count == 0:
            disc = Image.new("RGBA", high_disc_size, (0, 0, 0, 0))
            disc_draw = ImageDraw.Draw(disc)
            disc_draw.ellipse(
                scaled(disc_box),
                fill=SURFACE,
                outline=WHEEL_METAL,
                width=3 * scale,
            )
        else:
            high_center = disc_center * scale
            wedge_radius = (radius + 4) * scale
            disc_rgb = Image.new("RGB", high_disc_size, WHEEL_COLORS[0])
            wedge_draw = ImageDraw.Draw(disc_rgb)
            angle_offset = 0.0
            for index in range(active_count):
                segment = probabilities[index] * 360.0
                start = angle_offset
                steps = max(2, math.ceil(segment / 2.0))
                points = [(high_center, high_center)]
                for step in range(steps + 1):
                    angle = math.radians(start + segment * step / steps)
                    points.append(
                        (
                            round(high_center + wedge_radius * math.cos(angle)),
                            round(high_center - wedge_radius * math.sin(angle)),
                        )
                    )
                wedge_draw.polygon(
                    points,
                    fill=WHEEL_COLORS[index % len(WHEEL_COLORS)],
                )
                angle_offset += segment

            circle_mask = Image.new("L", high_disc_size, 0)
            ImageDraw.Draw(circle_mask).ellipse(scaled(disc_box), fill=255)
            disc = disc_rgb.convert("RGBA")
            disc.putalpha(circle_mask)
            disc_draw = ImageDraw.Draw(disc)

            if active_count > 1:
                angle_offset = 0.0
                for segment_probability in probabilities:
                    angle = math.radians(angle_offset)
                    endpoint = (
                        round(high_center + radius * scale * math.cos(angle)),
                        round(high_center - radius * scale * math.sin(angle)),
                    )
                    disc_draw.line(
                        (high_center, high_center, endpoint[0], endpoint[1]),
                        fill=WHEEL_SEPARATOR,
                        width=max(2, scale),
                    )
                    angle_offset += segment_probability * 360.0
        return disc.resize((disc_size, disc_size), Image.Resampling.LANCZOS)

    def _draw_metal_rim(
        self, draw: ImageDraw.ImageDraw, scale: int
    ) -> None:
        """Draw a clean layered metal rim without a noisy texture."""

        cx = self.CENTER_X * scale
        cy = self.CENTER_Y * scale
        radius = self.RADIUS * scale

        def rim_box(inset: float) -> tuple[int, int, int, int]:
            inset_scaled = inset * scale
            return (
                round(cx - radius + inset_scaled),
                round(cy - radius + inset_scaled),
                round(cx + radius - inset_scaled),
                round(cy + radius - inset_scaled),
            )

        draw.ellipse(rim_box(0), outline=WHEEL_METAL_SHADOW, width=2 * scale)
        draw.ellipse(rim_box(2), outline=WHEEL_METAL_DARK, width=10 * scale)
        draw.ellipse(rim_box(3), outline=WHEEL_METAL, width=7 * scale)
        draw.ellipse(
            rim_box(5), outline=WHEEL_METAL_LIGHT, width=max(scale, 1)
        )
        draw.ellipse(rim_box(8), outline=WHEEL_METAL, width=2 * scale)
        draw.ellipse(rim_box(10), outline=WHEEL_METAL_DARK, width=2 * scale)

    def _draw_static_center_emblem(
        self, overlay: Image.Image, scale: int
    ) -> None:
        """Draw the centre medallion and guild icon on the fixed overlay."""

        cx = self.CENTER_X * scale
        cy = self.CENTER_Y * scale
        radius = self.CENTER_MEDALLION_RADIUS * scale
        center_box = (
            round(cx - radius),
            round(cy - radius),
            round(cx + radius),
            round(cy + radius),
        )
        center_draw = ImageDraw.Draw(overlay)
        center_draw.ellipse(center_box, fill="#181C19")

        try:
            with Image.open(resource_path("imgs", "guild icon.png")) as source:
                icon = source.convert("RGBA")
            target_size = self.GUILD_ICON_SIZE * scale
            icon = icon.resize(
                (target_size, target_size), Image.Resampling.LANCZOS
            )
            icon_x = round(cx - icon.width / 2)
            icon_y = round(cy - icon.height / 2)
            overlay.alpha_composite(icon, (icon_x, icon_y))
        except (OSError, ValueError):
            # Keep the wheel usable even if an external development asset is absent.
            pass

        center_draw = ImageDraw.Draw(overlay)
        center_draw.ellipse(
            center_box,
            outline="#777F79",
            width=2 * scale,
        )
        inner_radius = radius - 5 * scale
        center_draw.ellipse(
            (
                round(cx - inner_radius),
                round(cy - inner_radius),
                round(cx + inner_radius),
                round(cy + inner_radius),
            ),
            outline=ACCENT,
            width=max(scale, 1),
        )

    def _ensure_static_wheel_assets(self) -> None:
        if hasattr(self, "_wheel_background") and hasattr(self, "_wheel_overlay"):
            return

        scale = self.ANTIALIAS_SCALE
        size = self.CANVAS_SIZE
        cx, cy, radius = self.CENTER_X, self.CENTER_Y, self.RADIUS
        high_size = (size * scale, size * scale)

        background = Image.new("RGB", high_size, BACKGROUND)

        overlay = Image.new("RGBA", high_size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        self._draw_metal_rim(overlay_draw, scale)
        self._draw_static_center_emblem(overlay, scale)
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.polygon(
            [
                (round((cx - 17) * scale), 5 * scale),
                (round((cx + 17) * scale), 5 * scale),
                (round(cx * scale), 44 * scale),
            ],
            fill=ACCENT,
            outline=ACCENT_DARK,
            width=2 * scale,
        )
        overlay_draw.line(
            [
                (round((cx - 14) * scale), 8 * scale),
                (round(cx * scale), 40 * scale),
            ],
            fill="#C7AF70",
            width=max(2, scale),
        )

        output_size = (size, size)
        self._wheel_background = background.resize(
            output_size, Image.Resampling.LANCZOS
        )
        disc_center = radius + 6
        self._wheel_disc_offset = (cx - disc_center, cy - disc_center)
        self._wheel_overlay = overlay.resize(output_size, Image.Resampling.LANCZOS)
