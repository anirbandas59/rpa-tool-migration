"""Engine module — transformation and annotation of Blue Prism stages."""

from flowsmith.engine.annotator import StageAnnotator, create_annotator
from flowsmith.engine.flag_index import (
    FlagEntry,
    FlagIndex,
    FlagIndexBuilder,
)
from flowsmith.engine.scorer import (
    PageScore,
    ProcessScore,
    ProcessScorer,
    StageSummary,
)

__all__ = [
    "StageAnnotator",
    "create_annotator",
    "StageSummary",
    "PageScore",
    "ProcessScore",
    "ProcessScorer",
    "FlagEntry",
    "FlagIndex",
    "FlagIndexBuilder",
]
