from zipfile import ZipFile

import scr.tools.md2docx as md2docx
from scr.tools.md2docx import markdown_to_docx


def _document_xml(docx_path):
    with ZipFile(docx_path) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def test_markdown_math_is_written_as_native_word_math(tmp_path):
    output_path = tmp_path / "math.docx"
    markdown = (
        "模型满足 $x_i^2 + \\frac{a}{b}$。"
        "\n\n"
        "$$ \\sum_{i=1}^{n} x_i \\leq 1 \\tag{1} $$"
    )

    markdown_to_docx(markdown, str(output_path))

    document_xml = _document_xml(output_path)
    assert "<m:oMath" in document_xml
    assert "<m:f" in document_xml
    assert "<m:sSubSup" in document_xml
    assert "$x_i" not in document_xml
    assert "$$" not in document_xml
    assert "<m:e></m:e>" not in document_xml


def test_convert_paper_falls_back_to_python_docx_without_pandoc(tmp_path, monkeypatch, capsys):
    markdown_path = tmp_path / "paper.md"
    markdown_path.write_text("# 测试报告\n\n正文。", encoding="utf-8")
    monkeypatch.setattr(md2docx, "pandoc_available", lambda: False)

    output_path = md2docx.convert_paper_md_to_docx(markdown_path)

    assert output_path.endswith("paper.docx")
    assert (tmp_path / "paper.docx").exists()
    assert "未检测到 Pandoc，使用 Python-docx 回退转换" in capsys.readouterr().out
