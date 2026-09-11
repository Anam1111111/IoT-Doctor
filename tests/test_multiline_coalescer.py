from core.parser.multiline import coalesce


def test_multiline_coalescer_basic():
    lines = [
        "Error: Something bad",
        "    at com.example.Main.method(Main.java:10)",
        "    at com.example.Lib.call(Lib.java:22)",
        "Info: other event",
    ]
    groups = coalesce(lines)
    assert len(groups) == 2
    assert groups[0][0].startswith("Error"), groups[0]
    assert len(groups[0]) == 3
    assert groups[1][0].startswith("Info") or groups[1][0].startswith("Info" )