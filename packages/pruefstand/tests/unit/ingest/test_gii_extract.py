"""Text extraction from GII `<norm>` content (T2.2): structure kept, footnotes dropped."""

from lxml import etree

from pruefstand.ingest.gii.extract import norm_text


def text_of(content: str) -> str:
    xml = f"<norm><textdaten><text><Content>{content}</Content></text></textdaten></norm>"
    return norm_text(etree.fromstring(xml))


def test_norm_without_text_is_empty() -> None:
    assert norm_text(etree.fromstring("<norm><metadaten/></norm>")) == ""
    assert norm_text(etree.fromstring("<norm><textdaten/></norm>")) == ""


def test_paragraphs_lists_and_breaks() -> None:
    out = text_of(
        "<P>(1) Erstens<BR/>zweite Zeile</P>"
        '<P>(2) Es gilt <DL Type="arabic"><DT>1.</DT><DD><LA>eins,</LA></DD>'
        "<DT>2.</DT><DD><LA>zwei.</LA></DD></DL>Danach weiter.</P>"
    )
    assert out.split("\n") == [
        "(1) Erstens", "zweite Zeile", "(2) Es gilt", "1. eins,", "2. zwei.", "Danach weiter.",
    ]  # fmt: skip


def test_nested_list_and_inline_markup() -> None:
    out = text_of(
        "<P>H<SUB>s,n</SUB> und <B>fett</B> <I>kursiv</I><DL><DT>a)</DT><DD><LA>x<DL><DT>aa)</DT>"
        "<DD><LA>tief</LA></DD></DL></LA></DD></DL></P>"
    )
    assert out.split("\n") == ["Hs,n und fett kursiv", "a) x", "aa) tief"]


def test_footnotes_images_and_comments_are_dropped_but_tails_stay() -> None:
    out = text_of(
        "<P>Vor<FnR ID='a'/> nach <IMG SRC='x.jpg'/>Bild<F Value='1'/> Ende"
        "<kommentar typ='Fundstelle'>(Fundstelle: BGBl.)</kommentar> fertig<!-- weg --></P>"
        "<Footnotes><Footnote ID='a'>Fußnote</Footnote></Footnotes>"
    )
    assert out == "Vor nach Bild Ende fertig"


def test_table_rows_use_pipes_and_skip_empty_rows() -> None:
    out = text_of(
        '<table><tgroup cols="3"><colspec colname="c1"/><thead><row><entry>Betrag</entry>'
        "<entry>Satz</entry><entry/></row></thead><tbody><row><entry>bis 1 500</entry>"
        "<entry>9\n  %</entry><entry/></row><row><entry/><entry/></row></tbody></tgroup></table>"
    )
    assert out.split("\n") == ["Betrag | Satz", "bis 1 500 | 9 %"]


def test_text_is_nfc_and_whitespace_normalised() -> None:
    out = text_of("<P>  Kündigung   und\n\n   Frist  </P>")
    assert out == "Kündigung und Frist"


def test_unknown_list_children_are_walked() -> None:
    out = text_of("<P><DL><DT>1.</DT><DD>x</DD><P>Zwischentext</P></DL></P>")
    assert out.split("\n") == ["1. x", "Zwischentext"]
