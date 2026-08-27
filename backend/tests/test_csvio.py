"""CSV ingestion: delimiters, encodings, malformed input and upload limits."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.utils.csvio import CSVParseError, read_csv, validate_upload


def write(tmp_path: Path, name: str, content: str, encoding: str = "utf-8") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding=encoding)
    return path


class TestValidateUpload:
    def test_accepts_csv(self):
        validate_upload("data.csv", 1024, max_bytes=10_000, allowed=(".csv",))

    def test_rejects_wrong_extension(self):
        with pytest.raises(CSVParseError, match="Unsupported file type"):
            validate_upload("payload.exe", 10, max_bytes=10_000, allowed=(".csv",))

    def test_rejects_empty_file(self):
        with pytest.raises(CSVParseError, match="empty"):
            validate_upload("data.csv", 0, max_bytes=10_000, allowed=(".csv",))

    def test_rejects_oversized_file(self):
        with pytest.raises(CSVParseError, match="limit"):
            validate_upload("data.csv", 20_000, max_bytes=10_000, allowed=(".csv",))

    def test_extension_check_is_case_insensitive(self):
        validate_upload("DATA.CSV", 100, max_bytes=10_000, allowed=(".csv",))


class TestDelimiterDetection:
    def test_comma(self, tmp_path):
        path = write(tmp_path, "a.csv", "x,y\n1,2\n3,4\n")
        result = read_csv(path)
        assert result.delimiter == ","
        assert list(result.frame.columns) == ["x", "y"]
        assert len(result.frame) == 2

    def test_semicolon(self, tmp_path):
        path = write(tmp_path, "a.csv", "x;y;z\n1;2;3\n4;5;6\n7;8;9\n")
        result = read_csv(path)
        assert result.delimiter == ";"
        assert result.frame.shape == (3, 3)

    def test_tab(self, tmp_path):
        path = write(tmp_path, "a.tsv", "x\ty\n1\t2\n3\t4\n5\t6\n")
        result = read_csv(path)
        assert result.delimiter == "\t"
        assert result.frame.shape == (3, 2)

    def test_pipe(self, tmp_path):
        path = write(tmp_path, "a.csv", "x|y|z\n1|2|3\n4|5|6\n7|8|9\n")
        result = read_csv(path)
        assert result.delimiter == "|"


class TestEncoding:
    def test_utf8_bom(self, tmp_path):
        path = write(tmp_path, "a.csv", "name,city\nJosé,München\n", encoding="utf-8-sig")
        result = read_csv(path)
        assert "José" in result.frame["name"].tolist()

    def test_latin1_fallback(self, tmp_path):
        path = tmp_path / "a.csv"
        path.write_bytes("name,city\nJosé,Köln\nAna,Berlin\n".encode("cp1252"))
        result = read_csv(path)
        assert len(result.frame) == 2


class TestMalformedInput:
    def test_empty_file_raises(self, tmp_path):
        path = write(tmp_path, "a.csv", "")
        with pytest.raises(CSVParseError):
            read_csv(path)

    def test_header_only_raises(self, tmp_path):
        path = write(tmp_path, "a.csv", "a,b,c\n")
        with pytest.raises(CSVParseError, match="no data rows"):
            read_csv(path)

    def test_ragged_rows_do_not_destroy_valid_rows(self, tmp_path):
        """An over-long row must not make pandas infer an index.

        Regression test: with index inference left on, this exact input
        collapsed to a single bogus row (`5,6`) and silently discarded both
        well-formed rows.
        """
        path = write(tmp_path, "a.csv", "a,b\n1,2\n3,4,5,6\n7,8\n")
        result = read_csv(path)
        assert result.frame["a"].tolist() == ["1", "3", "7"]
        assert result.frame["b"].tolist() == ["2", "4", "8"]
        assert any("more fields" in w for w in result.warnings)

    def test_duplicate_headers_are_renamed(self, tmp_path):
        path = write(tmp_path, "a.csv", "id,id,id\n1,2,3\n4,5,6\n")
        result = read_csv(path)
        # pandas disambiguates these itself (id, id.1, id.2); the contract the
        # rest of the pipeline depends on is simply that names are unique.
        assert len(set(result.frame.columns)) == 3

    def test_unnamed_columns_are_named(self, tmp_path):
        path = write(tmp_path, "a.csv", "a,,c\n1,2,3\n4,5,6\n")
        result = read_csv(path)
        assert all(str(c).strip() for c in result.frame.columns)

    def test_blank_rows_are_dropped(self, tmp_path):
        path = write(tmp_path, "a.csv", "a,b\n1,2\n,\n3,4\n")
        result = read_csv(path)
        assert len(result.frame) == 2

    def test_all_values_read_as_strings(self, tmp_path):
        """Type inference belongs to the profiler, not the reader."""
        path = write(tmp_path, "a.csv", "n,d\n007,2024-01-01\n008,2024-01-02\n")
        result = read_csv(path)
        assert result.frame["n"].iloc[0] == "007"  # leading zero preserved

    def test_na_tokens_become_missing(self, tmp_path):
        path = write(tmp_path, "a.csv", "a,b\n1,N/A\n2,NULL\n3,ok\n")
        result = read_csv(path)
        assert result.frame["b"].isna().sum() == 2


class TestRowLimit:
    def test_truncates_and_warns(self, tmp_path):
        rows = "\n".join(f"{i},{i * 2}" for i in range(50))
        path = write(tmp_path, "a.csv", f"a,b\n{rows}\n")
        result = read_csv(path, max_rows=10)
        assert len(result.frame) == 10
        assert result.truncated
        assert any("first 10" in w for w in result.warnings)
