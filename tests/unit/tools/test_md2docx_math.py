from zipfile import ZipFile

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
