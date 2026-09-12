from trade_copilot.ingestion.chunker import clean_text, split_pages
from trade_copilot.ingestion.loader import PageText


def test_clean_text_normalizes_whitespace() -> None:
    assert clean_text("标题\r\n\r\n\r\n正文   内容") == "标题\n\n正文 内容"


def test_split_pages_preserves_page_and_section() -> None:
    pages = [PageText(page=7, text="# 税务制度\n\n" + "税务内容。" * 300)]
    chunks = list(split_pages(pages, target_chars=200, overlap_chars=20))
    assert chunks
    assert all(page == 7 for page, _, _ in chunks)
    assert chunks[0][1] == "税务制度"

