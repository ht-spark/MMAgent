"""Markdown 转 DOCX 转换器 — 生成符合数学建模竞赛格式的 Word 文档。

功能：
  1. 解析 Markdown 文本（标题、段落、列表、表格、公式、图片引用）
  2. 生成格式化的 DOCX 文档：
     - 封面页（标题、摘要、关键词）
     - 自动编号的章节标题
     - 三线表格式
     - 居中图注
     - 居中公式（LaTeX → 文本近似）
     - 页码、页眉
  3. 嵌入实际图片文件（PNG）

依赖：python-docx
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml

__all__ = [
    "markdown_to_docx",
    "convert_paper_md_to_docx",
]


# ---------------------------------------------------------------------------
# Markdown 解析器
# ---------------------------------------------------------------------------

class MarkdownBlock:
    """Markdown 块级元素。"""
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    FORMULA = "formula"
    IMAGE = "image"
    LIST = "list"
    HORIZONTAL_RULE = "hr"

    def __init__(self, block_type: str, content: str, level: int = 0, **kwargs):
        self.block_type = block_type
        self.content = content
        self.level = level
        self.extra = kwargs


def parse_markdown(md_text: str) -> list[MarkdownBlock]:
    """将 Markdown 文本解析为块级元素列表。"""
    lines = md_text.split("\n")
    blocks: list[MarkdownBlock] = []
    i = 0

    while i < len(lines):
        line = lines[i].rstrip()

        # 空行跳过
        if not line.strip():
            i += 1
            continue

        # 标题
        heading_match = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            blocks.append(MarkdownBlock(MarkdownBlock.HEADING, title, level=level))
            i += 1
            continue

        # 水平线
        if re.match(r"^---+$", line.strip()):
            blocks.append(MarkdownBlock(MarkdownBlock.HORIZONTAL_RULE, ""))
            i += 1
            continue

        # 公式块 $$...$$
        if line.strip().startswith("$$"):
            formula_lines = [line.strip()]
            if not line.strip().endswith("$$") or line.strip() == "$$":
                i += 1
                while i < len(lines):
                    formula_lines.append(lines[i].rstrip())
                    if lines[i].strip().endswith("$$"):
                        break
                    i += 1
            formula_text = "\n".join(formula_lines)
            formula_text = formula_text.replace("$$", "").strip()
            blocks.append(MarkdownBlock(MarkdownBlock.FORMULA, formula_text))
            i += 1
            continue

        # 行内公式 \[...\]
        inline_formula = re.match(r"^\\\[([^\]]+)\\\]$", line.strip())
        if inline_formula:
            blocks.append(MarkdownBlock(MarkdownBlock.FORMULA, inline_formula.group(1).strip()))
            i += 1
            continue

        # 表格
        if line.startswith("|"):
            table_lines = [line]
            i += 1
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].rstrip())
                i += 1
            blocks.append(MarkdownBlock(MarkdownBlock.TABLE, "\n".join(table_lines)))
            continue

        # 图片引用 ![alt](path)
        img_match = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", line.strip())
        if img_match:
            alt = img_match.group(1)
            path = img_match.group(2)
            blocks.append(MarkdownBlock(MarkdownBlock.IMAGE, path, level=0, alt_text=alt))
            i += 1
            continue

        # 列表项
        list_match = re.match(r"^(\s*)([-*]|\d+\.)\s+(.+)$", line)
        if list_match:
            list_lines = [line]
            i += 1
            while i < len(lines):
                next_line = lines[i].rstrip()
                if re.match(r"^(\s*)([-*]|\d+\.)\s+", next_line):
                    list_lines.append(next_line)
                    i += 1
                elif next_line.strip() == "":
                    i += 1
                    # 检查下一行是否还是列表
                    if i < len(lines) and re.match(r"^(\s*)([-*]|\d+\.)\s+", lines[i].rstrip()):
                        continue
                    break
                else:
                    break
            blocks.append(MarkdownBlock(MarkdownBlock.LIST, "\n".join(list_lines)))
            continue

        # 普通段落（可能跨行直到空行或特殊行）
        para_lines = [line]
        i += 1
        while i < len(lines):
            next_line = lines[i].rstrip()
            if (not next_line.strip() or
                    next_line.startswith("#") or
                    next_line.startswith("|") or
                    next_line.startswith("$$") or
                    next_line.startswith("![") or
                    re.match(r"^---+$", next_line.strip()) or
                    re.match(r"^(\s*)([-*]|\d+\.)\s+", next_line)):
                break
            para_lines.append(next_line)
            i += 1
        blocks.append(MarkdownBlock(MarkdownBlock.PARAGRAPH, "\n".join(para_lines)))

    return blocks


# ---------------------------------------------------------------------------
# DOCX 生成器
# ---------------------------------------------------------------------------

class DocxBuilder:
    """构建 DOCX 文档。"""

    def __init__(self, output_path: str, base_dir: str = ""):
        self.doc = Document()
        self.output_path = output_path
        self.base_dir = base_dir
        self._figure_counter = 0
        self._table_counter = 0
        self._setup_styles()

    def _setup_styles(self):
        """设置文档默认样式。"""
        # 设置正文字体
        style = self.doc.styles["Normal"]
        font = style.font
        font.name = "宋体"
        font.size = Pt(12)
        style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

        # 设置段落间距
        pf = style.paragraph_format
        pf.space_after = Pt(6)
        pf.line_spacing = 1.5

        # 页面设置
        for section in self.doc.sections:
            section.top_margin = Cm(2.54)
            section.bottom_margin = Cm(2.54)
            section.left_margin = Cm(3.17)
            section.right_margin = Cm(3.17)

    def build(self, blocks: list[MarkdownBlock], title: str = ""):
        """从解析的块构建文档。"""
        # 添加标题页
        if title:
            self._add_title_page(title)

        # 处理每个块
        for block in blocks:
            self._process_block(block)

        # 添加页码
        self._add_page_numbers()

    def _add_title_page(self, title: str):
        """添加标题页。"""
        # 大标题
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(title)
        run.font.name = "黑体"
        run.font.size = Pt(22)
        run.bold = True
        run.font.color.rgb = RGBColor(0, 0, 0)
        p.paragraph_format.space_before = Pt(100)
        p.paragraph_format.space_after = Pt(30)

        self.doc.add_page_break()

    def _process_block(self, block: MarkdownBlock):
        """处理单个块。"""
        if block.block_type == MarkdownBlock.HEADING:
            self._add_heading(block.content, block.level)
        elif block.block_type == MarkdownBlock.PARAGRAPH:
            self._add_paragraph(block.content)
        elif block.block_type == MarkdownBlock.TABLE:
            self._add_table(block.content)
        elif block.block_type == MarkdownBlock.FORMULA:
            self._add_formula(block.content)
        elif block.block_type == MarkdownBlock.IMAGE:
            self._add_image(block.content, block.extra.get("alt_text", ""))
        elif block.block_type == MarkdownBlock.LIST:
            self._add_list(block.content)
        elif block.block_type == MarkdownBlock.HORIZONTAL_RULE:
            pass  # 忽略水平线

    def _add_heading(self, text: str, level: int):
        """添加标题。"""
        heading_levels = {
            1: ("黑体", 16, True),  # 一级标题
            2: ("黑体", 14, True),  # 二级标题
            3: ("黑体", 13, True),  # 三级标题
            4: ("黑体", 12, True),  # 四级标题
        }
        font_name, font_size, bold = heading_levels.get(level, ("黑体", 12, True))

        # 使用 Word 内置 heading 样式
        heading_style = f"Heading {min(level, 4)}"
        p = self.doc.add_paragraph(style=heading_style)
        run = p.add_run(text)
        run.font.name = font_name
        run.font.size = Pt(font_size)
        run.bold = bold
        run.font.color.rgb = RGBColor(0, 0, 0)
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(6)

    def _add_paragraph(self, text: str):
        """添加段落，处理行内格式。"""
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

        # 处理行内格式：粗体、斜体、行内公式
        self._add_formatted_runs(p, text)

    def _add_formatted_runs(self, paragraph, text: str):
        """添加格式化的文本运行（处理 **粗体**、*斜体*、$行内公式$）。"""
        # 分割文本，处理 **bold** 和 $formula$
        parts = re.split(r"(\*\*[^*]+\*\*|\$[^$]+\$|`[^`]+`)", text)

        for part in parts:
            if not part:
                continue
            if part.startswith("**") and part.endswith("**"):
                run = paragraph.add_run(part[2:-2])
                run.bold = True
            elif part.startswith("$") and part.endswith("$"):
                run = paragraph.add_run(part)
                run.italic = True
                run.font.name = "Cambria Math"
            elif part.startswith("`") and part.endswith("`"):
                run = paragraph.add_run(part[1:-1])
                run.font.name = "Consolas"
                run.font.size = Pt(10.5)
            else:
                paragraph.add_run(part)

    def _add_table(self, table_text: str):
        """添加三线表。"""
        lines = [l.strip() for l in table_text.split("\n") if l.strip().startswith("|")]
        if len(lines) < 2:
            return

        # 解析表格行
        rows_data: list[list[str]] = []
        for line in lines:
            # 跳过分隔行 |---|---|
            if re.match(r"^\|[\s\-:|]+\|$", line):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            rows_data.append(cells)

        if not rows_data:
            return

        n_cols = max(len(r) for r in rows_data)
        # 补齐短行
        for r in rows_data:
            while len(r) < n_cols:
                r.append("")

        # 创建表格
        table = self.doc.add_table(rows=len(rows_data), cols=n_cols)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER

        # 填充数据
        for i, row_data in enumerate(rows_data):
            for j, cell_text in enumerate(row_data):
                cell = table.cell(i, j)
                cell.text = ""
                p = cell.paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER

                # 处理加粗
                clean_text = cell_text
                bold = False
                if clean_text.startswith("**") and clean_text.endswith("**"):
                    clean_text = clean_text[2:-2]
                    bold = True

                run = p.add_run(clean_text)
                run.font.name = "宋体"
                run.font.size = Pt(10.5)

                # 表头加粗
                if i == 0 or bold:
                    run.bold = True

        # 三线表样式：顶部、表头下方、底部有线，其余无线
        self._format_three_line_table(table)

        self._table_counter += 1
        self.doc.add_paragraph()

    def _format_three_line_table(self, table):
        """设置三线表样式。"""
        tbl = table._tbl
        tblPr = tbl.tblPr if tbl.tblPr is not None else parse_xml(f'<w:tblPr {nsdecls("w")}/>')

        # 移除默认边框
        existing_borders = tblPr.find(qn("w:tblBorders"))
        if existing_borders is not None:
            tblPr.remove(existing_borders)

        # 设置三线表边框
        borders_xml = f'''<w:tblBorders {nsdecls("w")}>
            <w:top w:val="single" w:sz="12" w:space="0" w:color="000000"/>
            <w:bottom w:val="single" w:sz="12" w:space="0" w:color="000000"/>
            <w:left w:val="nil"/>
            <w:right w:val="nil"/>
            <w:insideH w:val="nil"/>
            <w:insideV w:val="nil"/>
        </w:tblBorders>'''
        tblPr.append(parse_xml(borders_xml))

        # 表头行底部添加边框
        if len(table.rows) > 1:
            first_row = table.rows[0]
            for cell in first_row.cells:
                tc = cell._tc
                tcPr = tc.get_or_add_tcPr()
                tcBorders = parse_xml(f'''<w:tcBorders {nsdecls("w")}>
                    <w:bottom w:val="single" w:sz="6" w:space="0" w:color="000000"/>
                </w:tcBorders>''')
                tcPr.append(tcBorders)

    def _add_formula(self, formula_text: str):
        """添加居中公式段落。"""
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)

        # 尝试将 LaTeX 转换为可读的 Unicode 数学符号
        readable = self._latex_to_unicode(formula_text)
        run = p.add_run(readable)
        run.font.name = "Cambria Math"
        run.font.size = Pt(12)
        run.italic = False

    def _latex_to_unicode(self, latex: str) -> str:
        """将 LaTeX 公式转换为 Unicode 近似文本。"""
        replacements = {
            # 希腊字母
            r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
            r"\epsilon": "ε", r"\zeta": "ζ", r"\eta": "η", r"\theta": "θ",
            r"\lambda": "λ", r"\mu": "μ", r"\nu": "ν", r"\xi": "ξ",
            r"\pi": "π", r"\rho": "ρ", r"\sigma": "σ", r"\tau": "τ",
            r"\phi": "φ", r"\chi": "χ", r"\psi": "ψ", r"\omega": "ω",
            r"\Gamma": "Γ", r"\Delta": "Δ", r"\Theta": "Θ", r"\Lambda": "Λ",
            r"\Sigma": "Σ", r"\Phi": "Φ", r"\Psi": "Ψ", r"\Omega": "Ω",
            r"\xi": "ξ", r"\eta": "η",
            # 数学运算符
            r"\sum": "∑", r"\prod": "∏", r"\int": "∫",
            r"\leq": "≤", r"\geq": "≥", r"\neq": "≠",
            r"\times": "×", r"\div": "÷", r"\pm": "±",
            r"\infty": "∞", r"\partial": "∂",
            r"\forall": "∀", r"\exists": "∃",
            r"\in": "∈", r"\notin": "∉", r"\subset": "⊂", r"\supset": "⊃",
            r"\cup": "∪", r"\cap": "∩", r"\emptyset": "∅",
            # 上下标相关
            r"\sqrt": "√",
            # 文本
            r"\text": "", r"\mathrm": "", r"\mathbf": "", r"\mathbb": "",
            r"\quad": "  ", r"\qquad": "    ",
            r"\left": "", r"\right": "",
            r"\cdot": "·", r"\ldots": "…", r"\cdots": "⋯",
            r"\hat": "", r"\bar": "", r"\tilde": "",
            r"\frac": "",
            r"\min": "min", r"\max": "max", r"\arg": "arg",
            r"\ln": "ln", r"\log": "log", r"\exp": "exp",
        }

        result = latex
        for latex_str, unicode_str in replacements.items():
            result = result.replace(latex_str, unicode_str)

        # 处理上下标 ^{...} 和 _{...}
        result = re.sub(r"\^\{([^}]+)\}", r"↑(\1)", result)
        result = re.sub(r"_\{([^}]+)\}", r"↓(\1)", result)
        result = re.sub(r"\^(\S)", r"↑\1", result)
        result = re.sub(r"_(\S)", r"↓\1", result)

        # 清理多余的花括号
        result = result.replace("{", "").replace("}", "")

        # 清理多余空格
        result = re.sub(r"  +", " ", result).strip()

        return result

    def _add_image(self, image_path: str, alt_text: str = ""):
        """添加图片（不自动添加图注，由 Markdown 正文中的图注段落处理）。"""
        # 尝试解析路径
        full_path = image_path
        if not Path(full_path).exists() and self.base_dir:
            full_path = str(Path(self.base_dir) / image_path)

        if not Path(full_path).exists():
            # 图片不存在，添加占位文本
            p = self.doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(f"[图片缺失: {image_path}]")
            run.italic = True
            run.font.color.rgb = RGBColor(128, 128, 128)
            return

        try:
            p = self.doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run()
            run.add_picture(full_path, width=Inches(5.5))
        except Exception as e:
            p = self.doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(f"[图片加载失败: {image_path} ({e})]")
            run.italic = True
            run.font.color.rgb = RGBColor(128, 128, 128)

    def _add_list(self, list_text: str):
        """添加列表。"""
        lines = list_text.split("\n")
        for line in lines:
            match = re.match(r"^(\s*)([-*]|\d+\.)\s+(.+)$", line)
            if match:
                indent = len(match.group(1))
                marker = match.group(2)
                content = match.group(3)

                is_ordered = re.match(r"\d+\.", marker)
                list_style = "List Number" if is_ordered else "List Bullet"

                p = self.doc.add_paragraph(style=list_style)
                self._add_formatted_runs(p, content)

                # 设置缩进
                if indent > 0:
                    p.paragraph_format.left_indent = Cm(indent * 0.5 + 0.75)

    def _add_page_numbers(self):
        """添加页码。"""
        for section in self.doc.sections:
            footer = section.footer
            footer_para = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
            footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

            # 添加页码字段
            run = footer_para.add_run()
            fldChar1 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="begin"/>')
            run._r.append(fldChar1)

            run2 = footer_para.add_run()
            instrText = parse_xml(f'<w:instrText {nsdecls("w")} xml:space="preserve"> PAGE </w:instrText>')
            run2._r.append(instrText)

            run3 = footer_para.add_run()
            fldChar2 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="end"/>')
            run3._r.append(fldChar2)

    def save(self):
        """保存文档。"""
        self.doc.save(self.output_path)
        print(f"[md2docx] DOCX 已保存: {self.output_path}")


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


def markdown_to_docx(
    md_text: str,
    output_path: str,
    title: str = "",
    base_dir: str = "",
) -> str:
    """将 Markdown 文本转换为 DOCX 文档。

    Args:
        md_text: Markdown 文本。
        output_path: 输出 DOCX 文件路径。
        title: 文档标题（用于封面页）。
        base_dir: 图片基准目录（用于解析相对路径）。

    Returns:
        输出文件路径。
    """
    blocks = parse_markdown(md_text)
    builder = DocxBuilder(output_path, base_dir=base_dir)
    builder.build(blocks, title=title)
    builder.save()
    return output_path


def convert_paper_md_to_docx(
    md_file_path: str,
    output_dir: str | None = None,
) -> str:
    """将论文 Markdown 文件转换为 DOCX。

    Args:
        md_file_path: Markdown 文件路径。
        output_dir: 输出目录（默认与 md 文件同目录）。

    Returns:
        输出 DOCX 文件路径。
    """
    md_path = Path(md_file_path)
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown 文件不存在: {md_file_path}")

    md_text = md_path.read_text(encoding="utf-8")

    # 从 Markdown 提取标题
    title = ""
    title_match = re.match(r"^#\s+(.+)$", md_text, re.MULTILINE)
    if title_match:
        title = title_match.group(1).strip()
        # 移除标题行，避免重复
        md_text = md_text.replace(title_match.group(0), "", 1)

    # 输出路径
    if output_dir is None:
        output_dir = str(md_path.parent)
    output_path = str(Path(output_dir) / f"{md_path.stem}.docx")

    # base_dir 用于解析图片路径
    base_dir = str(md_path.parent)

    return markdown_to_docx(
        md_text,
        output_path,
        title=title,
        base_dir=base_dir,
    )
