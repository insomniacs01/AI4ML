from __future__ import annotations

from backend.app.services.dataset_profile import build_dataset_profile


def test_dataset_profile_detects_semicolon_csv_and_decimal_comma(tmp_path) -> None:
    dataset = tmp_path / "air.csv"
    dataset.write_text(
        "\n".join(
            [
                "Date;Time;CO(GT);T;;",
                "10/03/2004;18.00.00;2,6;13,6;;",
                "11/03/2004;19.00.00;2;13,3;;",
            ]
        ),
        encoding="utf-8",
    )

    profile = build_dataset_profile(dataset)
    columns = {column.name: column for column in profile.columns}

    assert profile.row_count == 2
    assert profile.column_count == 4
    assert list(columns) == ["Date", "Time", "CO(GT)", "T"]
    assert columns["Date"].inferred_type == "datetime"
    assert columns["CO(GT)"].inferred_type == "number"
    assert columns["T"].inferred_type == "number"


def test_dataset_profile_bounds_column_scan_without_losing_row_count(tmp_path) -> None:
    dataset = tmp_path / "large.csv"
    rows = ["id,value", "1,10", "2,20"]
    rows.extend(f"{index},text-{index}" for index in range(3, 1003))
    dataset.write_text("\n".join(rows), encoding="utf-8")

    profile = build_dataset_profile(dataset, max_profile_rows=2)
    columns = {column.name: column for column in profile.columns}

    assert profile.row_count == 1002
    assert columns["value"].inferred_type == "integer"
    assert columns["value"].non_empty_count == 2
    assert len(profile.preview_rows) == 20


def test_dataset_profile_fast_row_count_respects_quoted_newlines(tmp_path) -> None:
    dataset = tmp_path / "quoted.csv"
    dataset.write_text('id,notes\n1,"hello\nworld"\n2,plain\n', encoding="utf-8")

    profile = build_dataset_profile(dataset, max_profile_rows=1)

    assert profile.row_count == 2
    assert profile.preview_rows[0]["notes"].replace("\r\n", "\n") == "hello\nworld"
