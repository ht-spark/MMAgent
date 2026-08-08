"""md2docx_pandoc 单元测试：Markdown + Pandoc → DOCX（公式转 Word 原生 OMML）。"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scr.tools.md2docx import (
    convert_paper_md_to_docx,
    find_pandoc,
    pandoc_available,
    pandoc_to_docx,
)

pytestmark = pytest.mark.skipif(
    not pandoc_available(),
    reason="pandoc 未安装（winget install JohnMacFarlane.Pandoc）",
)

SAMPLE_MD = """\
# 测试论文

## 1. 引言

行内公式 $x_i \\geq 0$，块公式：

$$
\\max \\sum_{i=1}^{n} c_i x_i \\quad \\text{s.t.} \\quad \\sum_{i=1}^{n} a_i x_i \\leq b \\tag{1}
$$

## 2. 表格

| 参数 | 含义 |
|------|------|
| x_i  | 决策变量 |
| c_i  | 收益系数 |

## 3. 图片

![测试图](figures/test.png)
"""


@pytest.fixture
def sample_md(tmp_path: Path) -> Path:
    md = tmp_path / "paper.md"
    md.write_text(SAMPLE_MD, encoding="utf-8")
    return md


class TestFindPandoc:
    def test_find_pandoc(self):
        assert find_pandoc() is not None
        assert pandoc_available() is True


class TestPandocToDocx:
    def test_converts_with_omml_formulas(self, sample_md: Path):
        out = sample_md.parent / "paper.docx"
        result = pandoc_to_docx(
            sample_md, out, resource_path=sample_md.parent
        )
        assert Path(result).exists()
        assert out.exists() and out.stat().st_size > 0

        with zipfile.ZipFile(out) as z:
            doc = z.read("word/document.xml").decode("utf-8", errors="replace")
            # 公式转为 Word 原生 OMML
            assert "oMath" in doc
            # 表格
            assert "w:tbl" in doc

    def test_embedded_image(self, tmp_path: Path):
        md = tmp_path / "paper.md"
        md.write_text("![图](figures/pic.png)", encoding="utf-8")
        (tmp_path / "figures").mkdir()
        (tmp_path / "figures" / "pic.png").write_bytes(b"fake-png")

        out = tmp_path / "paper.docx"
        pandoc_to_docx(md, out, resource_path=tmp_path)
        with zipfile.ZipFile(out) as z:
            doc = z.read("word/document.xml").decode("utf-8", errors="replace")
            assert "blip" in doc  # 图片已嵌入


class TestConvertPaperMdToDocx:
    def test_basic(self, sample_md: Path):
        result = convert_paper_md_to_docx(sample_md)
        assert Path(result).exists()
        assert result.endswith(".docx")

    def test_missing_file(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            convert_paper_md_to_docx(tmp_path / "nope.md")
