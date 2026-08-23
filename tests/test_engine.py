import tempfile
import shutil
from pathlib import Path
import pytest

from src.core.engine import DirectoryScanner, FileParser, FileInfo

def create_temp_file(tmp_path, name, content="test"):
    file_path = tmp_path / name
    file_path.write_text(content, encoding="utf-8")
    return file_path

def test_directory_scanner_basic(tmp_path):
    file_a = create_temp_file(tmp_path, "a.txt")
    file_b = create_temp_file(tmp_path, "b.log")
    scanner = DirectoryScanner(tmp_path, include_patterns=["*.txt"])
    files = scanner.scan()
    found_files = {f.name for f in files}
    assert "a.txt" in found_files
    assert "b.log" not in found_files

def test_directory_scanner_exclude(tmp_path):
    file_a = create_temp_file(tmp_path, "a.txt")
    file_b = create_temp_file(tmp_path, "b.txt")
    scanner = DirectoryScanner(tmp_path, include_patterns=["*.txt"], exclude_patterns=["b.txt"])
    files = scanner.scan()
    found_files = {f.name for f in files}
    assert "a.txt" in found_files
    assert "b.txt" not in found_files

def test_file_parser_txt(tmp_path):
    content = "Hello TidyDek"
    fpath = create_temp_file(tmp_path, "note.txt", content)
    parser = FileParser([".txt"])
    fileinfo = FileInfo(fpath)
    parsed = parser.parse(fileinfo)
    assert parsed["content"] == content


def test_file_parser_unsupported(tmp_path):
    fpath = create_temp_file(tmp_path, "data.md", "foo")
    parser = FileParser([".txt"])
    fileinfo = FileInfo(fpath)
    with pytest.raises(ValueError):
        parser.parse(fileinfo)
