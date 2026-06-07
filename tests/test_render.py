import os
import pytest
from PIL import Image

from budget_pace import render_png


def test_creates_file(tmp_path):
    out = str(tmp_path / "out.png")
    render_png(
        assigned=1800.0,
        spent=720.0,
        expected=900.0,
        pace_ratio=0.8,
        state_label="On Track",
        output_path=out,
    )
    assert os.path.exists(out)


def test_dimensions_gray4(tmp_path):
    out = str(tmp_path / "out.png")
    render_png(
        assigned=1800.0,
        spent=720.0,
        expected=900.0,
        pace_ratio=0.8,
        state_label="On Track",
        output_path=out,
        variant="gray4",
    )
    img = Image.open(out)
    assert img.size == (792, 272)
    assert img.mode == "L"


def test_dimensions_byr(tmp_path):
    out = str(tmp_path / "out.png")
    render_png(
        assigned=1800.0,
        spent=720.0,
        expected=900.0,
        pace_ratio=0.8,
        state_label="On Track",
        output_path=out,
        variant="byr",
    )
    img = Image.open(out)
    assert img.size == (792, 272)
    assert img.mode == "RGB"


def test_slow_down_state(tmp_path):
    # Just verify it doesn't raise for the most alarming state
    out = str(tmp_path / "out.png")
    render_png(
        assigned=1800.0,
        spent=2000.0,
        expected=900.0,
        pace_ratio=2.22,
        state_label="Slow down",
        output_path=out,
    )
    assert os.path.exists(out)


def test_zero_assigned(tmp_path):
    # Assigned = 0 edge case should not raise
    out = str(tmp_path / "out.png")
    render_png(
        assigned=0.0,
        spent=0.0,
        expected=0.0,
        pace_ratio=0.0,
        state_label="On Track",
        output_path=out,
    )
    assert os.path.exists(out)
