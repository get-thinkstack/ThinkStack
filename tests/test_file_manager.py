"""unit tests for infrastructure.file_manager (pdf storage + model seeding).

all filesystem roots are redirected to tmp dirs so nothing touches the real user
data directory. covers save/find/delete/list of pdfs and the first-run model
seeding (including its no-op and best-effort cases).
"""

import pytest

from config import settings
from infrastructure import file_manager


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    papers = tmp_path / "papers"
    data = tmp_path / "data"
    chroma = tmp_path / "vs"
    models = tmp_path / "models"
    for d in (papers, data, chroma, models):
        d.mkdir()
    monkeypatch.setattr(settings, "papers_dir", papers)
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "chroma_dir", chroma)
    monkeypatch.setattr(settings, "models_dir", models)
    return tmp_path


class TestPdfStorage:
    def test_save_returns_id_and_path(self, isolated_dirs):
        doc_id, path = file_manager.save_uploaded_pdf("paper.pdf", b"%PDF-1.4 data")
        assert len(doc_id) == 12
        assert path.exists() and path.read_bytes() == b"%PDF-1.4 data"
        assert path.name.startswith(doc_id)

    def test_get_pdf_path_finds_saved(self, isolated_dirs):
        doc_id, path = file_manager.save_uploaded_pdf("a.pdf", b"x")
        assert file_manager.get_pdf_path(doc_id) == path

    def test_get_pdf_path_missing_is_none(self, isolated_dirs):
        assert file_manager.get_pdf_path("nonexistent") is None

    def test_delete_existing(self, isolated_dirs):
        doc_id, path = file_manager.save_uploaded_pdf("a.pdf", b"x")
        assert file_manager.delete_pdf(doc_id) is True
        assert not path.exists()

    def test_delete_missing_returns_false(self, isolated_dirs):
        assert file_manager.delete_pdf("nonexistent") is False

    def test_list_stored_pdfs(self, isolated_dirs):
        file_manager.save_uploaded_pdf("alpha.pdf", b"x")
        file_manager.save_uploaded_pdf("beta.pdf", b"yy")
        listed = file_manager.list_stored_pdfs()
        assert len(listed) == 2
        names = {p["filename"] for p in listed}
        assert names == {"alpha.pdf", "beta.pdf"}
        assert all(p["size_bytes"] > 0 for p in listed)

    def test_list_ignores_non_pdf(self, isolated_dirs):
        (settings.papers_dir / "notes.txt").write_text("hi")
        assert file_manager.list_stored_pdfs() == []


class TestEnsureDirectories:
    def test_creates_all_roots(self, tmp_path, monkeypatch):
        for name in ("data_dir", "papers_dir", "chroma_dir", "models_dir"):
            monkeypatch.setattr(settings, name, tmp_path / name)
        monkeypatch.setattr(settings, "bundled_models_dir", tmp_path / "bundled")
        file_manager.ensure_directories()
        for name in ("data_dir", "papers_dir", "chroma_dir", "models_dir"):
            assert getattr(settings, name).is_dir()


class TestSeedBundledModels:
    def test_seeds_missing_models(self, tmp_path, monkeypatch):
        src = tmp_path / "bundled"
        dst = tmp_path / "models"
        src.mkdir()
        dst.mkdir()
        (src / "model.gguf").write_bytes(b"weights")
        monkeypatch.setattr(settings, "bundled_models_dir", src)
        monkeypatch.setattr(settings, "models_dir", dst)
        file_manager.seed_bundled_models()
        assert (dst / "model.gguf").read_bytes() == b"weights"

    def test_does_not_overwrite_existing(self, tmp_path, monkeypatch):
        src = tmp_path / "bundled"
        dst = tmp_path / "models"
        src.mkdir()
        dst.mkdir()
        (src / "model.gguf").write_bytes(b"new")
        (dst / "model.gguf").write_bytes(b"user-kept")
        monkeypatch.setattr(settings, "bundled_models_dir", src)
        monkeypatch.setattr(settings, "models_dir", dst)
        file_manager.seed_bundled_models()
        assert (dst / "model.gguf").read_bytes() == b"user-kept"

    def test_noop_when_source_equals_dest(self, tmp_path, monkeypatch):
        d = tmp_path / "models"
        d.mkdir()
        monkeypatch.setattr(settings, "bundled_models_dir", d)
        monkeypatch.setattr(settings, "models_dir", d)
        file_manager.seed_bundled_models()  # must not raise or recurse

    def test_noop_when_source_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "bundled_models_dir", tmp_path / "nope")
        monkeypatch.setattr(settings, "models_dir", tmp_path / "models")
        file_manager.seed_bundled_models()  # best-effort, no error
