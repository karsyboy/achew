import base64
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Literal

from ..core.config import get_settings
from ..models.local import LocalLibraryItem, LocalAudioFileInfo, LocalSplitItem

logger = logging.getLogger(__name__)

SUPPORTED_LOCAL_EXTENSIONS = {".m4b", ".m4a"}
FFPROBE_TIMEOUT_SECONDS = 120
FFPROBE_VALIDATE_TIMEOUT_SECONDS = 20
FFPROBE_CHAPTER_TIMEOUT_SECONDS = 20


@dataclass
class LocalResolvedItem:
    item_id: str
    name: str
    media_layout: Literal["single_file", "multi_file_grouped", "multi_file_individual"]
    audio_files: List[Path]
    rel_paths: List[str]
    durations: List[float]
    total_duration: float


def natural_sort_key(value: str):
    """Sort strings with embedded numbers in natural order."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def encode_rel_path(rel_path: str) -> str:
    raw = rel_path.encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_rel_path(encoded: str) -> str:
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    raw = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
    return raw.decode("utf-8")


def validate_local_root(root_path: str, media_base: str) -> Tuple[bool, str, Optional[Path]]:
    """Validate a configured local root path and enforce base-path sandboxing."""
    if not root_path.strip():
        return False, "Local root path is required", None

    try:
        base_path = Path(media_base).expanduser().resolve(strict=False)
        root = Path(root_path).expanduser().resolve(strict=False)
    except Exception as e:
        return False, f"Invalid path: {e}", None

    if not base_path.exists() or not base_path.is_dir():
        return False, f"Configured media base does not exist or is not a directory: {base_path}", None

    if not root.exists() or not root.is_dir():
        return False, f"Root path does not exist or is not a directory: {root}", None

    # Enforce strict root containment (with symlink-aware realpath checks).
    try:
        base_real = base_path.resolve(strict=True)
        root_real = root.resolve(strict=True)
    except Exception as e:
        return False, f"Failed to resolve real path: {e}", None

    if root_real != base_real and base_real not in root_real.parents:
        return False, f"Path must be inside sandbox base: {base_real}", None

    return True, "Valid local root path", root_real


class LocalLibraryService:
    def __init__(self, root_path: str, media_base: str):
        self.root_path = root_path
        self.media_base = media_base

        valid, message, resolved_root = validate_local_root(root_path, media_base)
        if not valid or not resolved_root:
            raise ValueError(message)

        self.root = resolved_root

    @classmethod
    def from_config(cls) -> "LocalLibraryService":
        from ..core.config import get_effective_local_root

        settings = get_settings()
        effective_root = get_effective_local_root()
        root_path = effective_root or settings.LOCAL_MEDIA_BASE
        return cls(root_path, settings.LOCAL_MEDIA_BASE)

    @staticmethod
    def build_item_id(kind: Literal["file", "folder"], rel_path: str) -> str:
        return f"{kind}::{encode_rel_path(rel_path)}"

    @staticmethod
    def parse_item_id(item_id: str) -> Tuple[str, str]:
        if "::" not in item_id:
            raise ValueError("Invalid local item id format")

        kind, encoded = item_id.split("::", 1)
        if kind not in {"file", "folder"}:
            raise ValueError("Invalid local item id kind")

        rel_path = decode_rel_path(encoded)
        return kind, rel_path

    def _audio_files_in_dir(self, directory: Path) -> List[Path]:
        files = []
        for entry in directory.iterdir():
            if entry.is_file() and entry.suffix.lower() in SUPPORTED_LOCAL_EXTENSIONS:
                files.append(entry)
        files.sort(key=lambda p: natural_sort_key(p.name))
        return files

    @staticmethod
    def _run_ffprobe(command: List[str], path: Path, timeout_seconds: int = FFPROBE_TIMEOUT_SECONDS) -> dict:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if result.returncode != 0:
            logger.warning(f"ffprobe failed for {path}: {result.stderr.strip()}")
            return {}

        try:
            return json.loads(result.stdout)
        except Exception as e:
            logger.warning(f"Failed parsing ffprobe output for {path}: {e}")
            return {}
        
    @staticmethod
    def _ffprobe_duration_json(path: Path) -> dict:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_entries",
            "format=duration",
            str(path),
        ]
        try:
            return LocalLibraryService._run_ffprobe(cmd, path)
        except subprocess.TimeoutExpired:
            logger.warning(f"ffprobe duration timed out for {path}")
            return {}

    @staticmethod
    def _ffprobe_chapters_json(path: Path) -> dict:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_chapters",
            str(path),
        ]
        try:
            return LocalLibraryService._run_ffprobe(cmd, path, timeout_seconds=FFPROBE_CHAPTER_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            logger.warning(f"ffprobe chapter probe timed out for {path}")
            return {}

    @staticmethod
    def _ffprobe_validation_json(path: Path) -> dict:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_entries",
            "format=duration,size:stream=index,codec_type,codec_name,duration",
            "-show_streams",
            str(path),
        ]
        try:
            return LocalLibraryService._run_ffprobe(cmd, path, timeout_seconds=FFPROBE_VALIDATE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            logger.warning(f"ffprobe validation timed out for {path}")
            return {}

    def get_audio_duration(self, path: Path) -> float:
        data = self._ffprobe_duration_json(path)
        try:
            return float(data.get("format", {}).get("duration", 0.0) or 0.0)
        except Exception:
            return 0.0

    def get_embedded_chapters(self, path: Path) -> List[Tuple[float, str]]:
        data = self._ffprobe_chapters_json(path)
        chapters = []
        for chapter in data.get("chapters", []):
            try:
                start = float(chapter.get("start_time", 0.0) or 0.0)
                tags = chapter.get("tags") or {}
                title = tags.get("title", "")
                chapters.append((start, title))
            except Exception:
                continue
        chapters.sort(key=lambda x: x[0])
        return chapters

    def validate_audio_file(self, path: Path) -> Tuple[bool, str, float]:
        """Validate basic readability and stream compatibility for local processing."""
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError:
            return False, f"File does not exist: {path}", 0.0
        except Exception as e:
            return False, f"Unable to resolve file path: {e}", 0.0

        if not resolved.is_file():
            return False, "Path is not a file", 0.0

        if resolved.suffix.lower() not in SUPPORTED_LOCAL_EXTENSIONS:
            return False, f"Unsupported file extension: {resolved.suffix}", 0.0

        if resolved.stat().st_size <= 0:
            return False, "File is empty", 0.0

        probe = self._ffprobe_validation_json(resolved)
        streams = probe.get("streams", [])
        audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
        if not audio_streams:
            return False, "No audio stream detected", 0.0

        duration = 0.0
        try:
            duration = float(probe.get("format", {}).get("duration", 0.0) or 0.0)
        except Exception:
            duration = 0.0

        if duration <= 0:
            # Fallback to the existing duration probe path.
            duration = self.get_audio_duration(resolved)

        if duration <= 0:
            return False, "Unable to determine audio duration", 0.0

        return True, "", duration

    def scan_items(self) -> List[LocalLibraryItem]:
        """Scan root recursively and return grouped-folder + standalone-file candidates."""
        consumed_files: set[Path] = set()
        grouped_items: List[LocalLibraryItem] = []

        for dirpath, dirnames, _ in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            directory = Path(dirpath)

            if directory == self.root:
                continue

            audio_files = self._audio_files_in_dir(directory)
            if len(audio_files) < 2:
                continue

            rel_dir = directory.relative_to(self.root).as_posix()
            file_infos: List[LocalAudioFileInfo] = []
            split_items: List[LocalSplitItem] = []
            total_duration = 0.0

            for audio_file in audio_files:
                consumed_files.add(audio_file.resolve())
                rel_file = audio_file.relative_to(self.root).as_posix()
                duration = self.get_audio_duration(audio_file)
                total_duration += duration

                file_infos.append(
                    LocalAudioFileInfo(
                        rel_path=rel_file,
                        filename=audio_file.name,
                        duration=duration,
                        size=audio_file.stat().st_size,
                    )
                )

                split_items.append(
                    LocalSplitItem(
                        id=self.build_item_id("file", rel_file),
                        name=audio_file.stem,
                        rel_path=rel_file,
                        file_count=1,
                        duration=duration,
                    )
                )

            grouped_items.append(
                LocalLibraryItem(
                    id=self.build_item_id("folder", rel_dir),
                    name=directory.name,
                    rel_path=rel_dir,
                    candidate_type="multi_file_folder_book",
                    processing_mode="multi_file_grouped",
                    file_count=len(audio_files),
                    duration=total_duration,
                    files=file_infos,
                    can_split=True,
                    individual_items=split_items,
                )
            )

        standalone_items: List[LocalLibraryItem] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            directory = Path(dirpath)
            for filename in filenames:
                if filename.startswith("."):
                    continue

                path = directory / filename
                if path.suffix.lower() not in SUPPORTED_LOCAL_EXTENSIONS:
                    continue

                resolved = path.resolve()
                if resolved in consumed_files:
                    continue

                rel_path = path.relative_to(self.root).as_posix()
                duration = self.get_audio_duration(path)
                standalone_items.append(
                    LocalLibraryItem(
                        id=self.build_item_id("file", rel_path),
                        name=path.stem,
                        rel_path=rel_path,
                        candidate_type="single_file_book",
                        processing_mode="single_file",
                        file_count=1,
                        duration=duration,
                        files=[
                            LocalAudioFileInfo(
                                rel_path=rel_path,
                                filename=path.name,
                                duration=duration,
                                size=path.stat().st_size,
                            )
                        ],
                        can_split=False,
                        individual_items=[],
                    )
                )

        all_items = grouped_items + standalone_items
        all_items.sort(key=lambda item: natural_sort_key(item.rel_path))
        return all_items

    def resolve_candidate(
        self,
        item_id: str,
        layout_hint: Optional[Literal["single_file", "multi_file_grouped", "multi_file_individual"]] = None,
    ) -> LocalResolvedItem:
        kind, rel_path = self.parse_item_id(item_id)

        # Prevent traversal via decoded IDs.
        if rel_path.startswith("/") or ".." in Path(rel_path).parts:
            raise ValueError("Invalid local item path")

        absolute = (self.root / rel_path).resolve(strict=True)
        if self.root != absolute and self.root not in absolute.parents:
            raise ValueError("Resolved path escaped configured root")

        if kind == "file":
            if not absolute.is_file():
                raise ValueError("Selected local item is not a file")
            if absolute.suffix.lower() not in SUPPORTED_LOCAL_EXTENSIONS:
                raise ValueError(f"Unsupported file extension: {absolute.suffix}")

            duration = self.get_audio_duration(absolute)
            media_layout: Literal["single_file", "multi_file_grouped", "multi_file_individual"] = (
                "multi_file_individual" if layout_hint == "multi_file_individual" else "single_file"
            )
            return LocalResolvedItem(
                item_id=item_id,
                name=absolute.stem,
                media_layout=media_layout,
                audio_files=[absolute],
                rel_paths=[rel_path],
                durations=[duration],
                total_duration=duration,
            )

        if not absolute.is_dir():
            raise ValueError("Selected local item is not a directory")

        audio_files = self._audio_files_in_dir(absolute)
        if len(audio_files) < 2:
            raise ValueError("Folder candidates require at least two supported audio files")

        durations = [self.get_audio_duration(path) for path in audio_files]
        rel_paths = [path.relative_to(self.root).as_posix() for path in audio_files]
        return LocalResolvedItem(
            item_id=item_id,
            name=absolute.name,
            media_layout="multi_file_grouped",
            audio_files=audio_files,
            rel_paths=rel_paths,
            durations=durations,
            total_duration=sum(durations),
        )
