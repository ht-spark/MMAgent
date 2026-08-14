from __future__ import annotations

import io
import zipfile

from KnowledgeBase import upload_file


def test_prepare_markdown_upload(monkeypatch, tmp_path):
    raw_root = tmp_path / "raw"
    documents_root = tmp_path / "documents"
    monkeypatch.setattr(upload_file, "RAW_ROOT", raw_root)
    monkeypatch.setattr(upload_file, "DOCUMENTS_ROOT", documents_root)

    prepared = upload_file.prepare_upload("reference.md", b"# Reference\n")

    assert [item.name for item in prepared] == ["reference.md"]
    assert (documents_root / "reference.md").read_text(encoding="utf-8") == "# Reference\n"


def test_prepare_zip_upload_expands_each_source(monkeypatch, tmp_path):
    raw_root = tmp_path / "raw"
    documents_root = tmp_path / "documents"
    monkeypatch.setattr(upload_file, "RAW_ROOT", raw_root)
    monkeypatch.setattr(upload_file, "DOCUMENTS_ROOT", documents_root)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("notes/a.md", "# A\n")
        bundle.writestr("notes/b.txt", "B\n")

    prepared = upload_file.prepare_upload("bundle.zip", archive.getvalue())

    assert {item.name for item in prepared} == {"bundle_a.md", "bundle_b.md"}
    assert (documents_root / "bundle_a.md").read_text(encoding="utf-8") == "# A\n"
    assert (documents_root / "bundle_b.md").read_text(encoding="utf-8") == "B\n"
