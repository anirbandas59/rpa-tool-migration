"""Data type mapper — Blue Prism scalar types to Power Automate equivalents.

Maps BP data types (text, number, flag, datetime, etc.) to their
Power Automate Desktop (.robin) and Cloud Flow (JSON) equivalents.

Type mappings are stable platform constants, not user-configurable rules.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from flowsmith.ast.models import BPDataItem, ReviewFlag


class TypeMapping(BaseModel):
    """The type mapping for a single Blue Prism data type.

    Immutable (frozen) once created. Contains the PAD and Cloud Flow
    equivalents for a given BP type, plus any review flags for lossy
    or unknown mappings.
    """

    model_config = ConfigDict(frozen=True)

    bp_type: str = Field(description="Original Blue Prism type string.")
    pad_type: str = Field(description="Power Automate Desktop (.robin) type.")
    cloud_type: str = Field(description="Cloud Flow JSON type.")
    is_known: bool = Field(description="True if BP type is recognized, False if defaulted.")
    review_flag: ReviewFlag | None = Field(
        default=None,
        description="Review flag for lossy or unknown mappings (severity=warn).",
    )


class DataTypeMapper:
    """Maps Blue Prism data types to Power Automate equivalents.

    All 11 known BP scalar types are mapped to PAD and Cloud Flow types.
    Unknown types return safe defaults (Text/string) with a review flag.
    Lossy mappings (password, object, timespan, binary, image) always
    receive a warn-level review flag.
    """

    # Stable platform type mappings — not user-configurable.
    # Format: bp_type -> (pad_type, cloud_type)
    _TYPE_MAP: dict[str, tuple[str, str]] = {
        "text": ("Text", "string"),
        "number": ("Number", "float"),
        "flag": ("Boolean", "boolean"),
        "datetime": ("DateTime", "string"),
        "date": ("DateTime", "string"),
        "timespan": ("Text", "string"),
        "binary": ("BinaryData", "string"),
        "image": ("BinaryData", "string"),
        "password": ("Text", "string"),
        "object": ("CustomObject", "object"),
        "collection": ("DataTable", "array"),
    }

    # Types that require a review flag due to lossy mapping.
    _LOSSY_TYPES = {"password", "object", "timespan", "binary", "image"}

    # Review flag reasons for lossy types.
    _LOSSY_REASONS = {
        "password": "Password stored as plain Text — migrate to Key Vault or environment secret",
        "object": "BP Object type has no direct PA equivalent — verify CustomObject usage",
        "timespan": "TimeSpan mapped to Text — verify formatting in downstream stages",
        "binary": "Binary data mapped to BinaryData/base64 — verify transfer size limits",
        "image": "Image mapped to BinaryData/base64 — verify transfer size limits",
    }

    def map_type(
        self,
        bp_type: str,
        stage_id: str = "",
    ) -> TypeMapping:
        """Map a Blue Prism data type to Power Automate equivalents.

        Performs case-insensitive lookup. Unknown types return safe defaults
        (Text for PAD, string for Cloud) with a review flag.

        Args:
            bp_type: Raw BP type string from XML (case-insensitive).
            stage_id: Optional stage_id for ReviewFlag.stage_id. Pass "" if
                not known at call time.

        Returns:
            TypeMapping with pad_type, cloud_type, and optional review_flag
            populated.

        Raises:
            Never raises. Unknown types return a safe default.
        """
        # Normalize to lowercase for case-insensitive lookup
        normalized = bp_type.lower()

        # Look up the type mapping
        if normalized in self._TYPE_MAP:
            pad_type, cloud_type = self._TYPE_MAP[normalized]
            is_known = True
        else:
            # Unknown type — return safe defaults
            pad_type = "Text"
            cloud_type = "string"
            is_known = False

        # Determine if a review flag is needed
        review_flag = None

        if not is_known:
            # Unknown types always get a review flag
            review_flag = ReviewFlag(
                stage_id=stage_id,
                reason=f"Unknown BP type '{bp_type}' — defaulted to Text/string",
                severity="warn",
                suggested_fix="Add type mapping to DataTypeMapper._TYPE_MAP",
            )
        elif normalized in self._LOSSY_TYPES:
            # Lossy types always get a review flag
            reason = self._LOSSY_REASONS.get(
                normalized,
                f"Lossy mapping for BP type '{bp_type}'",
            )
            review_flag = ReviewFlag(
                stage_id=stage_id,
                reason=reason,
                severity="warn",
                suggested_fix="Review type usage in downstream stages",
            )

        return TypeMapping(
            bp_type=bp_type,
            pad_type=pad_type,
            cloud_type=cloud_type,
            is_known=is_known,
            review_flag=review_flag,
        )

    def map_data_item(
        self,
        data_item: BPDataItem,
        stage_id: str = "",
    ) -> TypeMapping:
        """Convenience method — map type directly from a BPDataItem.

        Args:
            data_item: BPDataItem from the AST.
            stage_id: stage_id for ReviewFlag if needed.

        Returns:
            TypeMapping for data_item.data_type.
        """
        return self.map_type(data_item.data_type, stage_id=stage_id)
