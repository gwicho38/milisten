from milisten.chunk import chunk, pack, sentences


def test_sentences_split_on_terminators():
    out = sentences("First one. Second one! Third one? Fourth.")
    assert out == ("First one.", "Second one!", "Third one?", "Fourth.")


def test_sentences_do_not_split_inside_a_decimal():
    assert sentences("Rule 164.312 applies.") == ("Rule 164.312 applies.",)


def test_paragraph_breaks_do_not_merge_sentences():
    assert len(sentences("One para.\n\nTwo para.")) == 2


def test_pack_respects_target_but_never_splits_a_sentence():
    items = ("A" * 300 + ".", "B" * 300 + ".", "C" * 300 + ".")
    packed = pack(items, target=700)
    assert len(packed) == 2
    assert all(len(p) <= 1000 for p in packed)


def test_pack_breaks_a_single_oversize_sentence():
    monster = ", ".join(["clause"] * 800)
    packed = pack((monster,), target=900, hard_max=1000)
    assert len(packed) > 1
    assert all(len(p) <= 1000 for p in packed)


def test_pack_loses_no_words():
    items = ("Alpha beta.", "Gamma delta.", "Epsilon zeta.")
    words = " ".join(pack(items, target=20)).split()
    assert words == " ".join(items).split()


def test_chunk_indices_are_sequential():
    pieces = chunk("One. Two. Three.", target=5)
    assert [c.index for c in pieces] == list(range(len(pieces)))


def test_chunk_of_empty_text_is_empty():
    assert chunk("") == ()
