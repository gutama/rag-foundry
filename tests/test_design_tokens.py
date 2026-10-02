"""Tests for the Assay design tokens and the CSS generated from them."""

import copy
import importlib.util
import pathlib
import re

import pytest

_DESIGN_DIR = pathlib.Path(__file__).resolve().parents[1] / "design-system"


@pytest.fixture(name="build_tokens", scope="module")
def fixture_build_tokens():
    """Loads design-system/build_tokens.py, which is not an installed module."""
    spec = importlib.util.spec_from_file_location(
        "build_tokens", _DESIGN_DIR / "build_tokens.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="tokens", scope="module")
def fixture_tokens(build_tokens):
    """The committed design-system/tokens.json."""
    return build_tokens.load_tokens()


class TestContrastRatio:
    """Tests for the WCAG 2.x contrast calculation."""

    def test_black_on_white_is_21(self, build_tokens):
        """Black on white is the maximum ratio, 21:1."""
        ratio = build_tokens.contrast_ratio("#000000", "#ffffff")
        assert ratio == pytest.approx(21.0)

    def test_identical_colors_is_1(self, build_tokens):
        """A color against itself has no contrast."""
        assert build_tokens.contrast_ratio("#2d4fd6", "#2d4fd6") == 1.0

    def test_order_does_not_matter(self, build_tokens):
        """The ratio is symmetric in foreground and background."""
        forward = build_tokens.contrast_ratio("#5a6170", "#f2f3f5")
        backward = build_tokens.contrast_ratio("#f2f3f5", "#5a6170")
        assert forward == pytest.approx(backward)

    def test_known_pair(self, build_tokens):
        """White on cobalt-500 matches the 6.6:1 quoted in the spec."""
        ratio = build_tokens.contrast_ratio("#ffffff", "#2d4fd6")
        assert ratio == pytest.approx(6.6, abs=0.05)


class TestTokens:
    """Tests for the content of tokens.json."""

    def test_every_theme_color_has_a_dark_value(self, build_tokens, tokens):
        """Theme and status colors define both a light and a dark value."""
        for name, light, dark in build_tokens.iter_theme_colors(tokens):
            assert light, f"{name} has no light value"
            assert dark, f"{name} has no dark value"

    def test_colors_are_hex_or_transparent(self, build_tokens, tokens):
        """Every color is a 6-digit lowercase hex value or transparent."""
        pattern = re.compile(r"^#[0-9a-f]{6}$")
        colors = [
            value
            for _, light, dark in build_tokens.iter_theme_colors(tokens)
            for value in (light, dark)
        ]
        colors += [
            value for _, value in build_tokens.iter_palette_colors(tokens)
        ]
        for value in colors:
            assert value == "transparent" or pattern.match(value), value

    def test_contrast_requirements_hold(self, build_tokens, tokens):
        """Text, control and focus pairs meet WCAG AA in both themes."""
        failures = build_tokens.find_contrast_failures(tokens)
        assert not failures, "\n".join(failures)

    def test_status_colors_are_checked(self, build_tokens, tokens):
        """Every status contributes a foreground-on-background pair."""
        checked = {
            (fg, bg)
            for fg, bg, _ in build_tokens.contrast_requirements(tokens)
        }
        statuses = [name for name in tokens["status"] if name[0] != "$"]
        assert "approved" in statuses
        for status in statuses:
            assert (f"{status}-fg", f"{status}-bg") in checked, status

    def test_failing_pair_is_reported(self, build_tokens, tokens):
        """A muted text color too light for the light theme is caught."""
        broken = copy.deepcopy(tokens)
        broken["theme"]["fg-muted"]["$value"] = "#d5d9e0"
        failures = build_tokens.find_contrast_failures(broken)
        assert any("fg-muted" in f and "light" in f for f in failures)


class TestGeneratedFiles:
    """Tests that the committed CSS matches what tokens.json generates."""

    def test_tokens_css_is_up_to_date(self, build_tokens, tokens):
        """tokens.css was regenerated after the last tokens.json change."""
        expected = build_tokens.render_tokens_css(tokens)
        actual = (_DESIGN_DIR / "tokens.css").read_text(encoding="utf-8")
        assert actual == expected, "run: python design-system/build_tokens.py"

    def test_tailwind_css_is_up_to_date(self, build_tokens, tokens):
        """tailwind.css was regenerated after the last tokens.json change."""
        expected = build_tokens.render_tailwind_css(tokens)
        actual = (_DESIGN_DIR / "tailwind.css").read_text(encoding="utf-8")
        assert actual == expected, "run: python design-system/build_tokens.py"

    def test_tailwind_references_defined_properties(
        self, build_tokens, tokens
    ):
        """Every --rf-* property the Tailwind theme uses is defined."""
        defined = set(
            re.findall(
                r"(--rf-[a-z0-9-]+):", build_tokens.render_tokens_css(tokens)
            )
        )
        used = set(
            re.findall(
                r"var\((--rf-[a-z0-9-]+)\)",
                build_tokens.render_tailwind_css(tokens),
            )
        )
        assert used
        assert used <= defined, sorted(used - defined)

    def test_light_and_dark_values_reach_the_css(self, build_tokens, tokens):
        """Theme colors are emitted as light-dark() pairs."""
        css = build_tokens.render_tokens_css(tokens)
        assert "--rf-bg: light-dark(#f2f3f5, #0e1116);" in css
        assert "--rf-approved-fg: light-dark(#fff, #fff);" in css

    def test_build_writes_both_files(self, build_tokens, tokens, tmp_path):
        """Running the build writes tokens.css and tailwind.css."""
        assert build_tokens.main(["--out-dir", str(tmp_path)]) == 0
        css = (tmp_path / "tokens.css").read_text(encoding="utf-8")
        assert css == build_tokens.render_tokens_css(tokens)
        assert (tmp_path / "tailwind.css").exists()

    def test_check_mode_fails_on_stale_output(self, build_tokens, tmp_path):
        """--check exits non-zero when the generated files are missing."""
        assert build_tokens.main(["--check", "--out-dir", str(tmp_path)]) == 1

    def test_check_mode_passes_on_fresh_output(self, build_tokens, tmp_path):
        """--check exits zero right after a build."""
        build_tokens.main(["--out-dir", str(tmp_path)])
        assert build_tokens.main(["--check", "--out-dir", str(tmp_path)]) == 0
