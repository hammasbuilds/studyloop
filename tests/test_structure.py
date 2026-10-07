from conftest import TINY_BOOK

from studyloop.structure import parse_course, split_blocks, split_title, tile


def test_headings_become_chapters_and_topics():
    b = parse_course(TINY_BOOK)
    assert b.title == "A Small Book of Rivers"
    assert [c.title for c in b.chapters] == ["Chapter 1: Water Basics", "Chapter 2: Using Rivers"]
    assert [t.title for t in b.chapters[0].topics] == ["What a river is", "Floods"]
    assert [t.title for t in b.chapters[1].topics] == ["Power", "Transport"]


def test_every_paragraph_offset_indexes_the_source():
    b = parse_course(TINY_BOOK)
    for c in b.chapters:
        for t in c.topics:
            for p in t.paras:
                assert TINY_BOOK[p.start : p.end] == p.text


def test_title_with_dashes_gives_hints():
    short, hints = split_title("Lecture I: The Flame — Its Sources — Structure")
    assert short == "Lecture I" and hints == ["The Flame", "Its Sources", "Structure"]
    assert split_title("Plain title") == ("Plain title", [])


def test_headingless_long_chapter_is_segmented_and_named():
    words = ("river water flows " * 30 + "\n\n") * 6 + ("sediment delta farmland " * 30 + "\n\n") * 6
    md = "# Book\n\n## One\n\n" + words
    b = parse_course(md)
    topics = b.chapters[0].topics
    assert len(topics) >= 2
    for t in topics:
        assert t.title and t.n_words > 0


def test_short_chapter_without_subheadings_is_one_topic():
    md = "# B\n\n## Short\n\nOnly a few words here, nothing more to say about this at all today.\n"
    b = parse_course(md)
    assert len(b.chapters[0].topics) == 1


def test_no_headings_at_all_still_gives_a_course():
    b = parse_course("Just text. " * 40, "Loose notes")
    assert b.title == "Loose notes" and b.chapters


def test_code_fences_are_not_headings():
    md = "# T\n\n## A\n\n```\n# not a heading\n```\n\nSome words follow here for the text to count as prose.\n"
    b = parse_course(md)
    assert [c.title for c in b.chapters] == ["A"]


def test_tile_respects_k():
    paras = split_blocks("alpha beta gamma delta. " * 5 + "\n\n" + "x y z. " * 5, 0, 10**6)
    assert len(tile(paras * 4, 1)) == 1
