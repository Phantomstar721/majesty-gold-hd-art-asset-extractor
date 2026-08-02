import ast
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ffmpeg_support  # noqa: E402
import imaging  # noqa: E402

from extract_assets import (  # noqa: E402
    CURATED_INTERFACE_RECORDS,
    CamEntry,
    CamSection,
    ExtractionMode,
    OUTPUT_MARKER,
    bink_sample_frame_indices,
    cinematic_soundtrack_path,
    confirm_output_clear,
    decode_splash_picture,
    describe_existing_contents,
    decode_tile_v3,
    is_inside,
    is_palette_key_color,
    presentation_category,
    preview_cell_label,
    edge_connected_index_offsets,
    expected_tile_opaque_pixels,
    resolve_game_path,
    should_preserve_full_palette,
    should_recover_enclosed_transparency,
    steam_installdir,
    tile_v3_to_image,
    tile_v1_to_image,
    tile_to_category_image,
    validate_output_root,
)


class TileV3Tests(unittest.TestCase):
    def test_packed_count_supports_wide_menu_runs(self):
        # Full-screen interface TILEs use count values above 255. Count occupies
        # the low 11 bits and the end-of-row marker is bit 15.
        tile = _tile_v3(x_end=320, pixels=b"\x01" * 300, flags=0x80)

        decoded = decode_tile_v3(tile)

        self.assertIsNotNone(decoded)
        self.assertEqual(decoded["width"], 320)
        self.assertEqual(decoded["rows"], [[(20, [1] * 300)]])

    def test_clean_art_removes_phantom_shadow_transition_index(self):
        tile = _tile_v3(x_end=2, pixels=bytes((247, 1)), flags=0x80)
        palette = _palette_section({1: (10, 20, 30), 247: (156, 33, 24)})

        raw = tile_v3_to_image(tile, palette, clean_art=False)
        clean = tile_v3_to_image(tile, palette, clean_art=True)

        self.assertEqual(raw.size, (2, 1))
        self.assertEqual(raw.getpixel((0, 0)), (156, 33, 24, 255))
        self.assertEqual(clean.size, (1, 1))
        self.assertEqual(clean.getpixel((0, 0)), (10, 20, 30, 255))

    def test_reserved_shadow_range_starts_at_247(self):
        self.assertFalse(is_palette_key_color(246, 20, 30, 40))
        self.assertTrue(is_palette_key_color(247, 20, 30, 40))
        self.assertTrue(is_palette_key_color(250, 20, 30, 40))
        self.assertFalse(is_palette_key_color(251, 244, 243, 242))
        self.assertTrue(is_palette_key_color(251, 255, 42, 255))

    def test_palette_less_v3_rows_decode_as_16_bit_menu_art(self):
        header = bytearray(26)
        struct.pack_into("<HHH", header, 0, 3, 1, 2)
        offsets = struct.pack("<I", 4)
        segment = struct.pack("<HHHH", 2, 0x8002, 0x7C00, 0x001F)

        image = tile_v3_to_image(bytes(header) + offsets + segment, None)

        self.assertIsNotNone(image)
        self.assertEqual(image.size, (2, 1))

    def test_explicit_zero_inside_v3_run_is_an_opaque_palette_pixel(self):
        tile = _tile_v3(x_end=2, pixels=bytes((0, 1)), flags=0x80)
        palette = _palette_section({0: (254, 254, 254), 1: (10, 20, 30)})

        image = tile_v3_to_image(tile, palette, clean_art=True)

        self.assertEqual(image.size, (2, 1))
        self.assertEqual(image.getpixel((0, 0)), (254, 254, 254, 255))
        self.assertEqual(image.getpixel((1, 0)), (10, 20, 30, 255))
        self.assertEqual(
            expected_tile_opaque_pixels(tile, palette, "buildings/sprites", clean_art=True),
            2,
        )


class ExtractionModeTests(unittest.TestCase):
    def test_mode_contract(self):
        self.assertTrue(ExtractionMode.ALL_RAW.exhaustive)
        self.assertFalse(ExtractionMode.ALL_RAW.clean_art)
        self.assertFalse(ExtractionMode.RELEVANT_RAW.exhaustive)
        self.assertFalse(ExtractionMode.RELEVANT_RAW.clean_art)
        self.assertTrue(ExtractionMode.RELEVANT_ART.clean_art)


class PresentationArtTests(unittest.TestCase):
    def test_presentation_categories(self):
        self.assertEqual(presentation_category("QM17"), "maps/quest")
        self.assertEqual(presentation_category("MV06"), "cinematics")
        self.assertEqual(presentation_category("SPLH"), "loading_screens")
        self.assertIsNone(presentation_category("DATA"))

    def test_bink_samples_cover_first_and_last_frames(self):
        data = bytearray(40)
        data[4:8] = b"BIKh"
        struct.pack_into("<I", data, 12, 101)

        indices = bink_sample_frame_indices(bytes(data), sample_count=5)

        self.assertEqual(indices, [0, 25, 50, 75, 100])

    def test_video_only_credit_reels_use_menu_theme(self):
        with tempfile.TemporaryDirectory() as temp_value:
            game = Path(temp_value)
            theme = game / "Music" / "GeneralTheme.mp3"
            theme.parent.mkdir()
            theme.touch()
            self.assertEqual(cinematic_soundtrack_path(game, "MV01"), theme)
            self.assertEqual(cinematic_soundtrack_path(game, "mv06"), theme)
            self.assertIsNone(cinematic_soundtrack_path(game, "MV02"))

    def test_loading_picture_dimensions_are_decoded(self):
        data = bytearray(48 + 2 * 2 * 2)
        struct.pack_into("<I", data, 0, 1)
        struct.pack_into("<HH", data, 16, 2, 2)
        data[48:] = struct.pack("<4H", 0x001F, 0x03E0, 0x7C00, 0x7FFF)

        image = decode_splash_picture(bytes(data))

        self.assertIsNotNone(image)
        self.assertEqual(image.size, (2, 2))

    def test_paintings_keep_high_palette_indices_in_clean_mode(self):
        self.assertTrue(should_preserve_full_palette("profile_art/heroes"))
        self.assertTrue(should_preserve_full_palette("icons/items"))
        self.assertTrue(should_preserve_full_palette("spell_effects"))
        self.assertTrue(should_preserve_full_palette("segues"))
        self.assertTrue(should_preserve_full_palette("menus/main"))
        self.assertTrue(should_preserve_full_palette("maps/interface"))
        self.assertFalse(should_preserve_full_palette("heroes/sprites"))
        self.assertTrue(should_preserve_full_palette("icons/spells"))

    def test_only_edge_connected_pixels_are_treated_as_transparency(self):
        width, height = 320, 200
        pixels = bytearray([1] * (width * height))
        enclosed = 100 * width + 160
        pixels[enclosed] = 255
        self.assertEqual(edge_connected_index_offsets(pixels, width, height, width, 255), set())
        pixels[160] = 255
        connected = edge_connected_index_offsets(pixels, width, height, width, 255)
        self.assertIn(160, connected)
        self.assertNotIn(enclosed, connected)
        self.assertTrue(should_recover_enclosed_transparency("icons/heroes"))
        self.assertFalse(should_recover_enclosed_transparency("heroes/sprites"))

    def test_profile_painting_keeps_high_and_declared_transparent_colors(self):
        tile = bytearray(28 + 1032)
        struct.pack_into("<HHHH", tile, 0, 1, 1, 2, 2)
        struct.pack_into("<H", tile, 16, 255)
        struct.pack_into("<H", tile, 20, 1)
        struct.pack_into("<I", tile, 22, 28)
        tile[26:28] = bytes((247, 255))
        tile[28 + 8 + 247 * 4 : 28 + 12 + 247 * 4] = bytes((10, 20, 30, 0))
        tile[28 + 8 + 255 * 4 : 28 + 12 + 255 * 4] = bytes((240, 241, 242, 0))

        image = tile_v1_to_image(
            bytes(tile),
            None,
            clean_art=False,
            preserve_full_palette=True,
            force_opaque_palette=True,
        )

        self.assertEqual(image.getpixel((0, 0)), (10, 20, 30, 255))
        self.assertEqual(image.getpixel((1, 0)), (240, 241, 242, 255))

    def test_category_router_limits_sprite_cleanup_to_sprite_art(self):
        width, height = 4, 3
        palette_offset = 26 + width * height
        tile = bytearray(palette_offset + 1032)
        struct.pack_into("<HHHH", tile, 0, 1, height, width, width)
        struct.pack_into("<H", tile, 16, 255)
        struct.pack_into("<H", tile, 20, 1)
        struct.pack_into("<I", tile, 22, palette_offset)
        tile[26 : 26 + width * height] = bytes((1,) * (width * height))
        tile[26 + width + 1] = 247
        tile[26 + width + 2] = 255
        for index, color in {1: (5, 6, 7), 247: (10, 20, 30), 255: (240, 241, 242)}.items():
            start = palette_offset + 8 + index * 4
            tile[start : start + 4] = bytes((*color, 0))

        icon = tile_to_category_image(bytes(tile), None, "icons/items", clean_art=True)
        sprite = tile_to_category_image(bytes(tile), None, "heroes/sprites", clean_art=True)

        self.assertEqual(icon.getpixel((1, 1)), (10, 20, 30, 255))
        self.assertEqual(icon.getpixel((2, 1)), (240, 241, 242, 255))
        self.assertEqual(sprite.getpixel((1, 1))[3], 0)
        self.assertEqual(sprite.getpixel((2, 1))[3], 0)


class OutputSafetyTests(unittest.TestCase):
    """The output folder is wiped with rmtree, so this guard is the only thing
    between a mistyped --out and real data loss."""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.base = Path(self._temp.name)
        self.game = self.base / "game" / "Majesty HD"
        (self.game / "Data").mkdir(parents=True)
        (self.game / "Data" / "maindata.cam").touch()
        (self.game / "Data" / "interfacedata.cam").touch()
        self.addCleanup(self._temp.cleanup)

    def assertRefused(self, target: Path) -> None:
        with self.assertRaises(ValueError):
            validate_output_root(self.game, target)

    def assertAllowed(self, target: Path) -> None:
        validate_output_root(self.game, target)

    def test_new_and_empty_folders_are_allowed(self):
        self.assertAllowed(self.base / "does-not-exist-yet")
        empty = self.base / "empty"
        empty.mkdir()
        self.assertAllowed(empty)

    def test_folder_from_a_previous_run_is_allowed(self):
        previous = self.base / "previous"
        previous.mkdir()
        (previous / OUTPUT_MARKER).write_text("x", encoding="utf-8")
        (previous / "heroes").mkdir()
        self.assertAllowed(previous)

    def test_a_folder_the_user_chose_is_allowed_but_described(self):
        """Their folder, their call. The tool warns; it does not overrule.

        Refusing this outright was wrong: picking a folder you made and filled
        is a decision, not a typo.
        """
        theirs = self.base / "Majesty Asset Test"
        theirs.mkdir()
        (theirs / "notes.txt").write_bytes(b"x")
        (theirs / "old art").mkdir()
        self.assertAllowed(theirs)

        described = describe_existing_contents(theirs)
        self.assertIsNotNone(described)
        count, names = described
        self.assertEqual(count, 2)
        self.assertIn("old art/", names)
        self.assertIn("notes.txt", names)

    def test_nothing_to_describe_for_empty_or_our_own_folders(self):
        self.assertIsNone(describe_existing_contents(self.base / "missing"))
        empty = self.base / "empty-one"
        empty.mkdir()
        self.assertIsNone(describe_existing_contents(empty))
        ours = self.base / "ours-again"
        ours.mkdir()
        (ours / OUTPUT_MARKER).write_text("x", encoding="utf-8")
        (ours / "heroes").mkdir()
        self.assertIsNone(describe_existing_contents(ours))

    def test_the_confirmation_is_what_stops_an_unattended_delete(self):
        theirs = self.base / "with-files"
        theirs.mkdir()
        (theirs / "keep.txt").write_bytes(b"x")
        # No console to answer on, so it declines rather than deleting.
        self.assertFalse(confirm_output_clear(theirs))
        self.assertTrue(confirm_output_clear(theirs, assume_yes=True))

    def test_the_game_and_anything_around_it_is_refused(self):
        self.assertRefused(self.game)
        self.assertRefused(self.game / "Data")
        self.assertRefused(self.game.parent)

    def test_drive_root_is_refused(self):
        self.assertRefused(Path(Path.cwd().anchor))

    def test_windows_and_profile_folders_are_refused(self):
        for name in ("SystemRoot", "ProgramFiles", "USERPROFILE"):
            value = os.environ.get(name)
            if value:
                self.assertRefused(Path(value))

    def test_a_file_is_not_a_valid_output_folder(self):
        target = self.base / "a-file.txt"
        target.write_text("x", encoding="utf-8")
        self.assertRefused(target)

    def test_confirmation_is_not_needed_when_nothing_would_be_lost(self):
        missing = self.base / "nope"
        self.assertTrue(confirm_output_clear(missing))
        empty = self.base / "blank"
        empty.mkdir()
        self.assertTrue(confirm_output_clear(empty))
        marked = self.base / "marked"
        marked.mkdir()
        (marked / OUTPUT_MARKER).write_text("x", encoding="utf-8")
        (marked / "heroes").mkdir()
        self.assertTrue(confirm_output_clear(marked))

    def test_is_inside_is_case_insensitive_and_not_prefix_fooled(self):
        self.assertTrue(is_inside(Path(r"C:\Games\Majesty HD\Data"), Path(r"c:\games\majesty hd")))
        self.assertFalse(is_inside(Path(r"C:\Games\Majesty HD2"), Path(r"C:\Games\Majesty HD")))


class Rgb565BackgroundTests(unittest.TestCase):
    """RGB565 has no alpha, so 0x0000 is both pure black and the sprite cutout.

    Reading it as transparent everywhere removed 4.5% of the main menu backdrop
    while leaving pixels one step off black intact.
    """

    @staticmethod
    def _tile(values: list[int]) -> bytes:
        width, height = len(values), 1
        header = bytearray(26)
        struct.pack_into("<HHH", header, 0, 1, height, width)
        struct.pack_into("<H", header, 6, width * 2)
        return bytes(header) + b"".join(struct.pack("<H", v) for v in values)

    def test_background_art_keeps_its_black_pixels(self):
        tile = self._tile([0x0000, 0xF800, 0x0000])
        image = tile_v1_to_image(tile, None, preserve_full_palette=True)
        self.assertEqual(image.size, (3, 1))
        self.assertEqual(image.getpixel((0, 0)), (0, 0, 0, 255))
        self.assertEqual(image.getpixel((2, 0)), (0, 0, 0, 255))

    def test_sprite_art_still_cuts_out_on_black(self):
        tile = self._tile([0x0000, 0xF800, 0x0000])
        image = tile_v1_to_image(tile, None, preserve_full_palette=False)
        # Cropped to the one visible pixel.
        self.assertEqual(image.size, (1, 1))
        self.assertEqual(image.getpixel((0, 0))[3], 255)

    def test_near_black_survives_either_way(self):
        tile = self._tile([0x0001])
        for preserve in (True, False):
            image = tile_v1_to_image(tile, None, preserve_full_palette=preserve)
            self.assertEqual(image.getpixel((0, 0))[3], 255)

    def test_the_audit_agrees_with_the_renderer(self):
        tile = self._tile([0x0000, 0xF800, 0x0000])
        for category, expected in (("menus/main", 3), ("heroes/sprites", 1)):
            image = tile_to_category_image(tile, None, category, clean_art=True)
            opaque = sum(1 for a in image.convert("RGBA").getchannel("A").getdata() if a > 0)
            counted = expected_tile_opaque_pixels(tile, None, category, clean_art=True)
            self.assertEqual(opaque, expected, category)
            self.assertEqual(counted, expected, category)


class PreviewLabelTests(unittest.TestCase):
    def test_direction_is_included_so_cells_differ(self):
        first = preview_cell_label({"set": "Stand", "direction": "2", "frame": "0"})
        second = preview_cell_label({"set": "Stand", "direction": "3", "frame": "0"})
        self.assertEqual(first, "Stand d2 f0")
        self.assertNotEqual(first, second)

    def test_non_directional_rows_stay_short(self):
        self.assertEqual(preview_cell_label({"set": "Active", "direction": "", "frame": "1"}), "Active f1")

    def test_empty_row_still_gets_a_label(self):
        self.assertEqual(preview_cell_label({}), "frame")


class GameDiscoveryTests(unittest.TestCase):
    def test_explicit_game_folder_is_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SystemExit):
                resolve_game_path(Path(temp))

    def test_installdir_is_read_from_an_app_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            manifest = Path(temp) / "appmanifest_73230.acf"
            manifest.write_text('"AppState"\n{\n\t"installdir"\t\t"Majesty Renamed"\n}\n', encoding="utf-8")
            self.assertEqual(steam_installdir(manifest), "Majesty Renamed")

    def test_missing_manifest_is_not_an_error(self):
        self.assertIsNone(steam_installdir(Path("nope") / "appmanifest_73230.acf"))


class ImagingTests(unittest.TestCase):
    """The standard-library replacement for the slice of Pillow we used."""

    def test_png_round_trips_through_our_own_codec(self):
        image = imaging.Image.new("RGBA", (4, 3), (0, 0, 0, 0))
        image.putpixel((0, 0), (255, 0, 0, 255))
        image.putpixel((3, 2), (0, 128, 255, 128))
        decoded = imaging.decode_png(imaging.encode_png(image))
        self.assertEqual(decoded.size, (4, 3))
        self.assertEqual(decoded.getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(decoded.getpixel((3, 2)), (0, 128, 255, 128))
        self.assertEqual(decoded.getpixel((1, 1)), (0, 0, 0, 0))

    def test_png_survives_a_file_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "x.png"
            image = imaging.Image.new("RGBA", (2, 2), (10, 20, 30, 255))
            image.save(path)
            self.assertEqual(path.read_bytes()[:8], imaging.PNG_SIGNATURE)
            self.assertEqual(imaging.Image.open(path).tobytes(), image.tobytes())

    def test_every_png_filter_type_decodes(self):
        """Our writer only emits filter 0, but FFmpeg and other tools do not."""
        for filter_type in range(5):
            width, height = 3, 2
            raw = bytearray()
            for y in range(height):
                raw.append(filter_type)
                raw += bytes([0] * (width * 4)) if filter_type else bytes(
                    [9, 8, 7, 255] * width
                )
            body = zlib.compress(bytes(raw))

            def chunk(tag: bytes, payload: bytes) -> bytes:
                return (
                    struct.pack(">I", len(payload))
                    + tag
                    + payload
                    + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
                )

            data = (
                imaging.PNG_SIGNATURE
                + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", body)
                + chunk(b"IEND", b"")
            )
            self.assertEqual(imaging.decode_png(data).size, (width, height), filter_type)

    def test_getbbox_finds_the_tight_box(self):
        image = imaging.Image.new("RGBA", (6, 5), (0, 0, 0, 0))
        image.putpixel((2, 1), (1, 2, 3, 255))
        image.putpixel((4, 3), (1, 2, 3, 255))
        self.assertEqual(image.getbbox(), (2, 1, 5, 4))

    def test_getbbox_is_none_when_nothing_is_visible(self):
        self.assertIsNone(imaging.Image.new("RGBA", (3, 3), (0, 0, 0, 0)).getbbox())

    def test_crop_takes_the_requested_window(self):
        image = imaging.Image.new("RGBA", (4, 4), (0, 0, 0, 255))
        image.putpixel((2, 2), (9, 9, 9, 255))
        cropped = image.crop((1, 1, 3, 3))
        self.assertEqual(cropped.size, (2, 2))
        self.assertEqual(cropped.getpixel((1, 1)), (9, 9, 9, 255))

    def test_alpha_composite_blends_and_respects_transparency(self):
        base = imaging.Image.new("RGBA", (2, 1), (0, 0, 0, 255))
        top = imaging.Image.new("RGBA", (2, 1), (0, 0, 0, 0))
        top.putpixel((0, 0), (255, 255, 255, 255))
        base.alpha_composite(top)
        self.assertEqual(base.getpixel((0, 0)), (255, 255, 255, 255))
        self.assertEqual(base.getpixel((1, 0)), (0, 0, 0, 255))

    def test_nearest_resize_keeps_hard_edges(self):
        image = imaging.Image.new("RGBA", (2, 1), (0, 0, 0, 255))
        image.putpixel((1, 0), (255, 255, 255, 255))
        scaled = image.resize((4, 2), imaging.Resampling.NEAREST)
        self.assertEqual(scaled.size, (4, 2))
        self.assertEqual(scaled.getpixel((0, 0)), (0, 0, 0, 255))
        self.assertEqual(scaled.getpixel((3, 1)), (255, 255, 255, 255))

    def test_thumbnail_only_shrinks_and_keeps_aspect(self):
        image = imaging.Image.new("RGBA", (100, 50), (1, 2, 3, 255))
        image.thumbnail((50, 50))
        self.assertEqual(image.size, (50, 25))
        image.thumbnail((999, 999))
        self.assertEqual(image.size, (50, 25))

    def test_fifteen_bit_bgr_decodes(self):
        """The "BGR" in BGR;15 is byte order, not bit order.

        Bits 14-10 are red, 9-5 green, 4-0 blue. Reading the name as bit order
        gets the channels backwards, which is worth pinning: these values were
        checked against Pillow's own BGR;15 decoder and match on all four.
        """
        for value, expected in (
            (0x7C00, (255, 0, 0, 255)),
            (0x03E0, (0, 255, 0, 255)),
            (0x001F, (0, 0, 255, 255)),
            (0x7FFF, (255, 255, 255, 255)),
        ):
            image = imaging.Image.frombytes("RGB", (1, 1), struct.pack("<H", value), "raw", "BGR;15")
            self.assertEqual(image.getpixel((0, 0)), expected, hex(value))

    def test_flip_top_bottom(self):
        image = imaging.Image.new("RGBA", (1, 2), (0, 0, 0, 255))
        image.putpixel((0, 0), (255, 0, 0, 255))
        flipped = image.transpose(imaging.Transpose.FLIP_TOP_BOTTOM)
        self.assertEqual(flipped.getpixel((0, 1)), (255, 0, 0, 255))

    def test_text_draws_something_legible(self):
        image = imaging.Image.new("RGBA", (60, 12), (0, 0, 0, 255))
        imaging.ImageDraw.Draw(image).text((1, 2), "Stand d2", fill=(255, 255, 255, 255))
        lit = sum(1 for pixel in image.getdata() if pixel[:3] == (255, 255, 255))
        self.assertGreater(lit, 20)

    def test_unknown_characters_do_not_crash(self):
        image = imaging.Image.new("RGBA", (40, 12), (0, 0, 0, 255))
        imaging.ImageDraw.Draw(image).text((0, 0), "é中", fill=(255, 255, 255, 255))

    def test_the_font_covers_everything_the_tool_prints(self):
        """A missing glyph draws a fallback box, which is how a comma went
        unnoticed until it showed up as 17[]801 in a generated label."""
        needed = (
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789"
            " .,:;-_/()[]'\"!?#%+=*&<>|@$~^\\"
        )
        missing = sorted(set(needed) - set(imaging._GLYPHS))
        self.assertEqual(missing, [], f"glyphs missing from the bitmap font: {missing}")


class VideoCategoryTests(unittest.TestCase):
    """Which categories genuinely need FFmpeg.

    The tick-box and its messages once claimed segues needed FFmpeg. They do
    not: segues are ordinary interface records. Measured against a real
    install, a run with FFmpeg hidden produced 136 segues and 93 interface
    maps, identical to a run with it, while cinematics and quest maps went to
    zero.
    """

    NEEDS_FFMPEG = {"cinematics", "maps/quest"}

    def test_only_pict_records_can_need_ffmpeg(self):
        """Bink only ever arrives through presentation_category."""
        for name, category in (
            ("MV01", "cinematics"),
            ("QM07", "maps/quest"),
            ("SPLH", "loading_screens"),
        ):
            self.assertEqual(presentation_category(name), category)
        # Segue records are interface art and are not presentation records.
        for name in ("DXS0", "INDb", "IX72", "MX29"):
            self.assertIsNone(presentation_category(name), name)

    def test_segues_are_interface_records_not_video(self):
        segue_ids = [
            key for key, value in CURATED_INTERFACE_RECORDS.items() if value == "segues"
        ]
        self.assertTrue(segue_ids, "no segue records found; the mapping moved")
        for record_id in segue_ids:
            self.assertIsNone(presentation_category(record_id), record_id)

    def test_loading_screens_do_not_need_ffmpeg(self):
        """They are a 15-bit raster this tool decodes itself."""
        self.assertNotIn("loading_screens", self.NEEDS_FFMPEG)

    def test_the_wording_does_not_overclaim(self):
        """Nothing shown to the user should say segues need FFmpeg."""
        surfaces = [
            ffmpeg_support.describe_download(),
            "\n".join(ffmpeg_support.skip_notice()),
        ]
        for text in surfaces:
            lowered = text.lower()
            if "ffmpeg" in lowered:
                self.assertNotIn("segue", lowered, text)


class ProgressWordingTests(unittest.TestCase):
    """The window's progress markers are matched against the extractor's output.

    That coupling is invisible: reword a print() and the bar silently stops
    advancing. It already happened once, when "Extracting maps, cinematics"
    stopped matching after the message was corrected.
    """

    @staticmethod
    def _gui():
        import extractor_gui  # noqa: PLC0415 -- needs tkinter, so import late

        return extractor_gui

    @staticmethod
    def _printed_strings() -> list[str]:
        source = (SCRIPTS / "extract_assets.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        found: list[str] = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "print"):
                continue
            for argument in node.args:
                # Plain literals and the literal halves of f-strings.
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    found.append(argument.value)
                elif isinstance(argument, ast.JoinedStr):
                    found.append(
                        "".join(
                            part.value
                            for part in argument.values
                            if isinstance(part, ast.Constant) and isinstance(part.value, str)
                        )
                    )
        return found

    def test_every_marker_matches_something_the_extractor_prints(self):
        printed = self._printed_strings()
        self.assertTrue(printed, "no print() strings found; the parse broke")
        orphans = [
            marker
            for marker, _percent, _label in self._gui().PROGRESS_STAGES
            if not any(marker in line for line in printed)
        ]
        self.assertEqual(orphans, [], f"progress markers matching no output: {orphans}")

    def test_progress_only_moves_forward(self):
        percents = [percent for _m, percent, _l in self._gui().PROGRESS_STAGES]
        self.assertEqual(percents, sorted(percents))
        self.assertLessEqual(max(percents), 100)

    def test_status_wording_stays_out_of_the_internals(self):
        jargon = ("TILE", "IMAG", "CAM", "RLE", "SPLT", "PICT", "palette", "audit", "record")
        leaks = [
            label
            for _m, _p, label in self._gui().PROGRESS_STAGES
            if any(word in label for word in jargon)
        ]
        self.assertEqual(leaks, [], f"status text exposing internals: {leaks}")

    def test_mode_cards_avoid_internal_vocabulary(self):
        jargon = ("TILE", "IMAG", "CAM archive", "RLE", "SPLT", "PICT", "source-audit")
        offenders = []
        for mode, content in self._gui().MODE_CONTENT.items():
            for field in ("title", "summary", "includes", "detail"):
                text = content[field]
                for word in jargon:
                    if word in text:
                        offenders.append(f"{mode.value}.{field}: {word}")
        self.assertEqual(offenders, [], f"mode cards exposing internals: {offenders}")


class NoConsoleFlashTests(unittest.TestCase):
    """Child processes must not pop a console window.

    A packaged build is a GUI app with no console, so Windows gives every child
    a new one. An extraction runs FFmpeg about forty times, which appeared as a
    stream of command prompts flashing over the window.
    """

    def test_ffmpeg_runner_suppresses_the_window(self):
        source = (SCRIPTS / "ffmpeg_support.py").read_text(encoding="utf-8")
        self.assertIn("CREATE_NO_WINDOW", source)
        self.assertIn("STARTF_USESHOWWINDOW", source)
        self.assertIn("SW_HIDE", source)

    def test_nothing_calls_subprocess_directly(self):
        """Every launch goes through ffmpeg_support.run, which hides the window."""
        offenders = []
        for path in SCRIPTS.glob("*.py"):
            if path.name == "ffmpeg_support.py":
                continue  # the one place allowed to call subprocess
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "subprocess"
                ):
                    offenders.append(f"{path.name}:{node.lineno} subprocess.{func.attr}")
        self.assertEqual(
            offenders,
            [],
            "these would flash a console window; use ffmpeg_support.run: " + ", ".join(offenders),
        )

    def test_the_runner_actually_works(self):
        """Guard flags must not break the call itself."""
        result = ffmpeg_support.run([sys.executable, "-c", "print('hello')"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode().strip(), "hello")


class FFmpegSupportTests(unittest.TestCase):
    def test_nothing_is_downloaded_unless_asked(self):
        self.assertIsNone(
            ffmpeg_support.resolve_ffmpeg(
                allow_download=False,
                confirm=lambda _message: self.fail("must not prompt"),
            )
            if ffmpeg_support.find_ffmpeg() is None
            else None
        )

    def test_declining_the_prompt_skips_cinematics(self):
        if ffmpeg_support.find_ffmpeg() is not None:
            self.skipTest("FFmpeg is installed on this machine")
        self.assertIsNone(
            ffmpeg_support.resolve_ffmpeg(allow_download=True, confirm=lambda _message: False)
        )

    def test_the_prompt_names_the_source_and_destination(self):
        message = ffmpeg_support.describe_download()
        self.assertIn(ffmpeg_support.FFMPEG_URL, message)
        self.assertIn(str(ffmpeg_support.FFMPEG_DIR), message)
        self.assertTrue(ffmpeg_support.FFMPEG_URL.startswith("https://"))

    def test_an_explicit_override_is_honoured(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / "ffmpeg.exe"
            fake.write_bytes(b"")
            previous = os.environ.get("MAJESTY_FFMPEG")
            os.environ["MAJESTY_FFMPEG"] = str(fake)
            try:
                if not ffmpeg_support.FFMPEG_EXE.is_file():
                    self.assertEqual(ffmpeg_support.find_ffmpeg(), fake)
            finally:
                if previous is None:
                    os.environ.pop("MAJESTY_FFMPEG", None)
                else:
                    os.environ["MAJESTY_FFMPEG"] = previous


def _tile_v3(*, x_end: int, pixels: bytes, flags: int) -> bytes:
    header = bytearray(26)
    struct.pack_into("<HHH", header, 0, 3, 1, x_end)
    struct.pack_into("<I", header, 22, 0)
    offsets = struct.pack("<I", 4)
    count_flags = len(pixels) | (flags << 8)
    segment = struct.pack("<HH", x_end, count_flags) + pixels
    return bytes(header) + offsets + segment


def _palette_section(colors: dict[int, tuple[int, int, int]]) -> CamSection:
    data = bytearray(1032)
    for index, (red, green, blue) in colors.items():
        pos = 8 + index * 4
        data[pos : pos + 4] = bytes((red, green, blue, 0))
    return CamSection("SPLT", (CamEntry(b"palette".ljust(20, b"\0"), bytes(data), 0),))


if __name__ == "__main__":
    unittest.main()
