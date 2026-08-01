from pathlib import Path
import struct
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from extract_assets import (  # noqa: E402
    CamEntry,
    CamSection,
    ExtractionMode,
    bink_sample_frame_indices,
    cinematic_soundtrack_path,
    decode_splash_picture,
    decode_tile_v3,
    is_palette_key_color,
    presentation_category,
    edge_connected_index_offsets,
    expected_tile_opaque_pixels,
    should_preserve_full_palette,
    should_recover_enclosed_transparency,
    tile_v3_to_image,
    tile_v1_to_image,
    tile_to_category_image,
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
