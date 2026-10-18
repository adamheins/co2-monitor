from co2_monitor.parsing import parse_line


def test_parses_esphome_log_line():
    assert parse_line("[I][main:042]: DATA,680,22.52,55.71") == (680.0, 22.52, 55.71)


def test_parses_line_with_ansi_colour_codes():
    line = "\x1b[0;32m[I][main:042]: DATA,1138,22.74,52.79\x1b[0m\r\n"
    assert parse_line(line) == (1138.0, 22.74, 52.79)


def test_nan_reading_is_skipped():
    assert parse_line("[I][main:042]: DATA,nan,nan,nan") is None


def test_other_log_output_is_skipped():
    assert parse_line("[I][app:100]: Running through setup()...") is None
