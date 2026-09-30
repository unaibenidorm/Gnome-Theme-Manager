import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from gnome_theme_manager.api import _is_git_repo_url
from gnome_theme_manager.installer import extract_archive


class ArchiveSecurityTests(unittest.TestCase):
    def test_extracts_a_safe_zip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "theme.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("theme/index.theme", "[Theme]")

            output_dir = root / "output"
            extract_archive(archive_path, output_dir)
            self.assertEqual((output_dir / "theme/index.theme").read_text(), "[Theme]")

    def test_rejects_zip_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../outside", "blocked")

            with self.assertRaises(ValueError):
                extract_archive(archive_path, root / "output")

    def test_rejects_tar_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "unsafe.tar"
            with tarfile.open(archive_path, "w") as archive:
                payload = b"blocked"
                member = tarfile.TarInfo("../outside")
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))

            with self.assertRaises(ValueError):
                extract_archive(archive_path, root / "output")


class UrlValidationTests(unittest.TestCase):
    def test_only_recognizes_known_git_hosts(self):
        self.assertTrue(_is_git_repo_url("https://github.com/owner/repository"))
        self.assertFalse(_is_git_repo_url("https://github.com.example/owner/repository"))
        self.assertFalse(_is_git_repo_url("file:///etc/passwd"))


if __name__ == "__main__":
    unittest.main()
