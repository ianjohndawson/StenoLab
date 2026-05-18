from logic.frequency_importer import parse_frequency_text


def test_parses_space_tab_and_csv_frequency_rows():
    text = "\n".join([
        "word POS freq",
        "the ART 100",
        "and\tCONJ\t90",
        "rank,word,freq",
        "1,hello,42",
    ])

    assert parse_frequency_text(text) == {
        "the": 100,
        "and": 90,
        "hello": 42,
    }


def test_keeps_highest_duplicate_frequency_and_normalizes_words():
    text = "\n".join([
        "Hello! 10",
        "hello 25",
        "*can't* 15",
        "bad -2",
        "nanword nan",
        "infword inf",
    ])

    assert parse_frequency_text(text) == {
        "hello": 25,
        "can't": 15,
    }
