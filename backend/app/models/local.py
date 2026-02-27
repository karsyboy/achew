from typing import List, Literal

from pydantic import BaseModel, Field


class LocalAudioFileInfo(BaseModel):
    rel_path: str
    filename: str
    duration: float = 0.0
    size: int = 0


class LocalSplitItem(BaseModel):
    id: str
    name: str
    rel_path: str
    file_count: int = 1
    duration: float = 0.0


class LocalLibraryItem(BaseModel):
    id: str
    name: str
    rel_path: str
    candidate_type: Literal["single_file_book", "multi_file_folder_book"]
    processing_mode: Literal["single_file", "multi_file_grouped"]
    file_count: int = 1
    duration: float = 0.0
    files: List[LocalAudioFileInfo] = Field(default_factory=list)
    can_split: bool = False
    individual_items: List[LocalSplitItem] = Field(default_factory=list)
