"""Tests for flowsmith.mapper.type_mapper — Blue Prism data type mapping."""

from __future__ import annotations

import pytest

from flowsmith.ast import BPDataItem
from flowsmith.mapper import DataTypeMapper

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def mapper() -> DataTypeMapper:
    """Create a DataTypeMapper instance."""
    return DataTypeMapper()


@pytest.fixture
def make_data_item():
    """Factory for creating BPDataItem objects."""

    def _make(data_type: str = "text", name: str = "test_var") -> BPDataItem:
        return BPDataItem(
            name=name,
            data_type=data_type,
            initial_value=None,
            is_input=False,
            is_output=False,
        )

    return _make


# ── TypeMapping model tests ────────────────────────────────────────────────


class TestTypeMapping:
    """Test TypeMapping Pydantic model."""

    def test_type_mapping_is_frozen(self, mapper: DataTypeMapper) -> None:
        """TypeMapping is frozen — cannot modify fields."""
        mapping = mapper.map_type("text")
        with pytest.raises((TypeError, Exception)):
            mapping.pad_type = "NewType"  # type: ignore

    def test_type_mapping_has_all_fields(self, mapper: DataTypeMapper) -> None:
        """TypeMapping has all expected fields."""
        mapping = mapper.map_type("text")
        assert hasattr(mapping, "bp_type")
        assert hasattr(mapping, "pad_type")
        assert hasattr(mapping, "cloud_type")
        assert hasattr(mapping, "is_known")
        assert hasattr(mapping, "review_flag")


# ── Known types tests ──────────────────────────────────────────────────────


class TestKnownTypes:
    """Test mapping of all 11 known Blue Prism types."""

    @pytest.mark.parametrize(
        "bp_type",
        [
            "text",
            "number",
            "flag",
            "datetime",
            "date",
            "timespan",
            "binary",
            "image",
            "password",
            "object",
            "collection",
        ],
    )
    def test_all_known_types_is_known_true(self, mapper: DataTypeMapper, bp_type: str) -> None:
        """All 11 known types have is_known=True."""
        mapping = mapper.map_type(bp_type)
        assert mapping.is_known is True

    @pytest.mark.parametrize(
        "bp_type,expected_pad",
        [
            ("text", "Text"),
            ("number", "Number"),
            ("flag", "Boolean"),
            ("datetime", "DateTime"),
            ("date", "DateTime"),
            ("timespan", "Text"),
            ("binary", "BinaryData"),
            ("image", "BinaryData"),
            ("password", "Text"),
            ("object", "CustomObject"),
            ("collection", "DataTable"),
        ],
    )
    def test_pad_type_mapping(
        self, mapper: DataTypeMapper, bp_type: str, expected_pad: str
    ) -> None:
        """All 11 types map correctly to PAD types."""
        mapping = mapper.map_type(bp_type)
        assert mapping.pad_type == expected_pad

    @pytest.mark.parametrize(
        "bp_type,expected_cloud",
        [
            ("text", "string"),
            ("number", "float"),
            ("flag", "boolean"),
            ("datetime", "string"),
            ("date", "string"),
            ("timespan", "string"),
            ("binary", "string"),
            ("image", "string"),
            ("password", "string"),
            ("object", "object"),
            ("collection", "array"),
        ],
    )
    def test_cloud_type_mapping(
        self, mapper: DataTypeMapper, bp_type: str, expected_cloud: str
    ) -> None:
        """All 11 types map correctly to Cloud types."""
        mapping = mapper.map_type(bp_type)
        assert mapping.cloud_type == expected_cloud

    def test_map_type_text(self, mapper: DataTypeMapper) -> None:
        """text → Text / string"""
        m = mapper.map_type("text")
        assert m.pad_type == "Text"
        assert m.cloud_type == "string"

    def test_map_type_number(self, mapper: DataTypeMapper) -> None:
        """number → Number / float (not integer)"""
        m = mapper.map_type("number")
        assert m.pad_type == "Number"
        assert m.cloud_type == "float"

    def test_map_type_collection(self, mapper: DataTypeMapper) -> None:
        """collection → DataTable / array"""
        m = mapper.map_type("collection")
        assert m.pad_type == "DataTable"
        assert m.cloud_type == "array"


# ── Case-insensitive matching tests ────────────────────────────────────────


class TestCaseInsensitiveMatching:
    """Test case-insensitive type lookups."""

    def test_case_insensitive_text(self, mapper: DataTypeMapper) -> None:
        """Uppercase TEXT matches text."""
        mapping = mapper.map_type("TEXT")
        assert mapping.is_known is True
        assert mapping.pad_type == "Text"

    def test_case_insensitive_flag(self, mapper: DataTypeMapper) -> None:
        """Mixed case Flag matches flag."""
        mapping = mapper.map_type("Flag")
        assert mapping.is_known is True
        assert mapping.pad_type == "Boolean"

    def test_case_insensitive_collection(self, mapper: DataTypeMapper) -> None:
        """Uppercase COLLECTION matches collection."""
        mapping = mapper.map_type("COLLECTION")
        assert mapping.is_known is True
        assert mapping.pad_type == "DataTable"

    def test_case_insensitive_datetime(self, mapper: DataTypeMapper) -> None:
        """Mixed case DateTime matches datetime."""
        mapping = mapper.map_type("DateTime")
        assert mapping.is_known is True
        assert mapping.pad_type == "DateTime"


# ── Lossy type tests ───────────────────────────────────────────────────────


class TestLossyTypes:
    """Test lossy mappings that require review flags."""

    @pytest.mark.parametrize("lossy_type", ["password", "object", "timespan", "binary", "image"])
    def test_lossy_types_have_warn_flag(self, mapper: DataTypeMapper, lossy_type: str) -> None:
        """All lossy types have a review flag."""
        mapping = mapper.map_type(lossy_type)
        assert mapping.review_flag is not None

    @pytest.mark.parametrize("lossy_type", ["password", "object", "timespan", "binary", "image"])
    def test_lossy_flag_severity_is_warn(self, mapper: DataTypeMapper, lossy_type: str) -> None:
        """All lossy type flags have severity='warn'."""
        mapping = mapper.map_type(lossy_type)
        assert mapping.review_flag.severity == "warn"

    def test_lossy_flag_stage_id_populated(self, mapper: DataTypeMapper) -> None:
        """Lossy type flag has correct stage_id."""
        mapping = mapper.map_type("password", stage_id="test_stage")
        assert mapping.review_flag.stage_id == "test_stage"

    def test_password_pad_is_text(self, mapper: DataTypeMapper) -> None:
        """password → Text (not SecureString)"""
        mapping = mapper.map_type("password")
        assert mapping.pad_type == "Text"
        assert mapping.cloud_type == "string"

    def test_object_pad_is_custom_object(self, mapper: DataTypeMapper) -> None:
        """object → CustomObject"""
        mapping = mapper.map_type("object")
        assert mapping.pad_type == "CustomObject"
        assert mapping.cloud_type == "object"

    def test_timespan_pad_is_text(self, mapper: DataTypeMapper) -> None:
        """timespan → Text (no native timespan in PAD)"""
        mapping = mapper.map_type("timespan")
        assert mapping.pad_type == "Text"
        assert mapping.cloud_type == "string"


# ── Clean type tests ───────────────────────────────────────────────────────


class TestCleanTypes:
    """Test types without lossy mappings."""

    @pytest.mark.parametrize(
        "clean_type", ["text", "number", "flag", "datetime", "date", "collection"]
    )
    def test_clean_types_have_no_flag(self, mapper: DataTypeMapper, clean_type: str) -> None:
        """Clean types have no review flag."""
        mapping = mapper.map_type(clean_type)
        assert mapping.review_flag is None


# ── Unknown type tests ─────────────────────────────────────────────────────


class TestUnknownTypes:
    """Test behavior for unrecognized types."""

    def test_unknown_type_is_known_false(self, mapper: DataTypeMapper) -> None:
        """Unknown type has is_known=False."""
        mapping = mapper.map_type("weirdtype")
        assert mapping.is_known is False

    def test_unknown_type_pad_default_is_text(self, mapper: DataTypeMapper) -> None:
        """Unknown type defaults to Text for PAD."""
        mapping = mapper.map_type("unknowntype")
        assert mapping.pad_type == "Text"

    def test_unknown_type_cloud_default_is_string(self, mapper: DataTypeMapper) -> None:
        """Unknown type defaults to string for Cloud."""
        mapping = mapper.map_type("unknowntype")
        assert mapping.cloud_type == "string"

    def test_unknown_type_has_warn_flag(self, mapper: DataTypeMapper) -> None:
        """Unknown type has a review flag."""
        mapping = mapper.map_type("unknowntype")
        assert mapping.review_flag is not None

    def test_unknown_type_flag_severity_is_warn(self, mapper: DataTypeMapper) -> None:
        """Unknown type flag has severity='warn'."""
        mapping = mapper.map_type("unknowntype")
        assert mapping.review_flag.severity == "warn"

    def test_unknown_type_flag_mentions_type_name(self, mapper: DataTypeMapper) -> None:
        """Unknown type flag reason mentions the type name."""
        mapping = mapper.map_type("weirdtype")
        assert "weirdtype" in mapping.review_flag.reason

    def test_unknown_type_flag_stage_id_populated(self, mapper: DataTypeMapper) -> None:
        """Unknown type flag has correct stage_id."""
        mapping = mapper.map_type("unknowntype", stage_id="s99")
        assert mapping.review_flag.stage_id == "s99"

    def test_unknown_type_never_raises(self, mapper: DataTypeMapper) -> None:
        """Unknown types never raise exceptions."""
        try:
            mapping = mapper.map_type("this_type_definitely_does_not_exist")
            assert mapping is not None
        except Exception as e:
            pytest.fail(f"map_type raised an exception: {e}")


# ── map_data_item convenience method tests ─────────────────────────────────


class TestMapDataItem:
    """Test the map_data_item convenience method."""

    def test_map_data_item_delegates_to_map_type(
        self, mapper: DataTypeMapper, make_data_item
    ) -> None:
        """map_data_item delegates correctly to map_type."""
        item = make_data_item(data_type="number")
        result = mapper.map_data_item(item)
        direct = mapper.map_type("number")
        assert result.pad_type == direct.pad_type
        assert result.cloud_type == direct.cloud_type

    def test_map_data_item_passes_stage_id(self, mapper: DataTypeMapper, make_data_item) -> None:
        """map_data_item passes stage_id to map_type."""
        item = make_data_item(data_type="password")
        result = mapper.map_data_item(item, stage_id="test_stage")
        assert result.review_flag.stage_id == "test_stage"

    def test_map_data_item_text(self, mapper: DataTypeMapper, make_data_item) -> None:
        """map_data_item works for text type."""
        item = make_data_item(data_type="text")
        result = mapper.map_data_item(item)
        assert result.pad_type == "Text"
        assert result.cloud_type == "string"

    def test_map_data_item_collection(self, mapper: DataTypeMapper, make_data_item) -> None:
        """map_data_item works for collection type."""
        item = make_data_item(data_type="collection")
        result = mapper.map_data_item(item)
        assert result.pad_type == "DataTable"
        assert result.cloud_type == "array"

    def test_map_data_item_unknown(self, mapper: DataTypeMapper, make_data_item) -> None:
        """map_data_item works for unknown types."""
        item = make_data_item(data_type="weird_custom_type")
        result = mapper.map_data_item(item)
        assert result.is_known is False
        assert result.pad_type == "Text"


# ── Integration tests ──────────────────────────────────────────────────────


class TestIntegration:
    """Integration tests."""

    def test_mapper_has_all_11_types(self, mapper: DataTypeMapper) -> None:
        """Mapper contains exactly 11 known types."""
        # Access the private _TYPE_MAP to verify it has 11 entries
        assert len(mapper._TYPE_MAP) == 11

    def test_mapper_has_5_lossy_types(self, mapper: DataTypeMapper) -> None:
        """Mapper identifies exactly 5 lossy types."""
        assert len(mapper._LOSSY_TYPES) == 5

    def test_mapper_lossy_types_in_map(self, mapper: DataTypeMapper) -> None:
        """All lossy types are in the type map."""
        for lossy_type in mapper._LOSSY_TYPES:
            assert lossy_type in mapper._TYPE_MAP

    def test_mapper_lossy_types_have_reasons(self, mapper: DataTypeMapper) -> None:
        """All lossy types have reason messages."""
        for lossy_type in mapper._LOSSY_TYPES:
            assert lossy_type in mapper._LOSSY_REASONS
            assert len(mapper._LOSSY_REASONS[lossy_type]) > 0
