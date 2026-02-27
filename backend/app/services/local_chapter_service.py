import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)


class LocalChapterService:
    MP4_FAMILY_EXTENSIONS = {".m4b", ".m4a", ".mp4"}

    @staticmethod
    def validate_grouped_boundary_mapping(
        selected_starts: List[float],
        expected_starts: List[float],
        tolerance: float = 0.75,
    ) -> Tuple[bool, str]:
        if len(selected_starts) != len(expected_starts):
            return (
                False,
                f"Grouped multi-file write requires {len(expected_starts)} selected chapters "
                f"(got {len(selected_starts)}).",
            )

        for idx, selected_start in enumerate(selected_starts):
            if abs(selected_start - expected_starts[idx]) > tolerance:
                return (
                    False,
                    "Grouped multi-file write requires chapter timestamps to align with file boundaries.",
                )

        return True, ""

    @staticmethod
    def _get_duration(file_path: Path) -> float:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")

        try:
            return float(result.stdout.strip())
        except Exception as e:
            raise RuntimeError(f"Unable to parse duration for {file_path}: {e}") from e

    @staticmethod
    def _backup_path(file_path: Path) -> Path:
        return file_path.with_name(f"{file_path.name}.achew.bak")

    @staticmethod
    def _create_backup(file_path: Path) -> Path:
        backup = LocalChapterService._backup_path(file_path)
        shutil.copy2(file_path, backup)
        return backup

    @staticmethod
    def _run_ffmpeg(command: List[str]):
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ffmpeg command failed")

    @staticmethod
    def _output_muxer(file_path: Path) -> str | None:
        """Return an explicit muxer when extension-based auto-detect is problematic."""
        if file_path.suffix.lower() in LocalChapterService.MP4_FAMILY_EXTENSIONS:
            # Force mp4 muxer so ffmpeg does not pick the stricter 'ipod' muxer for .m4b.
            return "mp4"
        return None

    @staticmethod
    def _build_ffmetadata(chapters: List[Tuple[float, str]], duration: float) -> str:
        if not chapters:
            raise ValueError("No chapters provided")

        # Sort and normalize chapter starts.
        ordered = sorted(chapters, key=lambda c: c[0])
        if ordered[0][0] > 0:
            first_title = ordered[0][1]
            ordered[0] = (0.0, first_title)

        lines = [";FFMETADATA1"]
        for i, (start, title) in enumerate(ordered):
            end = duration if i == len(ordered) - 1 else ordered[i + 1][0]
            start_ms = max(0, int(round(start * 1000)))
            end_ms = max(start_ms, int(round(end * 1000)))
            safe_title = (title or "").replace("\n", " ").strip()

            lines.extend(
                [
                    "[CHAPTER]",
                    "TIMEBASE=1/1000",
                    f"START={start_ms}",
                    f"END={end_ms}",
                    f"title={safe_title}",
                ]
            )
        return "\n".join(lines) + "\n"

    @staticmethod
    def write_single_file_chapters(
        file_path: str,
        chapters: List[Tuple[float, str]],
        create_backup: bool = False,
    ):
        input_path = Path(file_path)
        if not input_path.exists() or not input_path.is_file():
            raise FileNotFoundError(f"File not found: {input_path}")

        duration = LocalChapterService._get_duration(input_path)
        ffmetadata = LocalChapterService._build_ffmetadata(chapters, duration)

        if create_backup:
            LocalChapterService._create_backup(input_path)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".ffmeta", delete=False, encoding="utf-8") as meta_file:
            meta_file.write(ffmetadata)
            metadata_path = meta_file.name

        tmp_output = input_path.with_name(f"{input_path.stem}.achew.tmp{input_path.suffix}")

        try:
            command = [
                "ffmpeg",
                "-y",
                "-i",
                str(input_path),
                "-f",
                "ffmetadata",
                "-i",
                metadata_path,
                "-map",
                "0:a",
                "-map",
                "0:v?",
                "-map_metadata",
                "0",
                "-map_chapters",
                "1",
                "-c",
                "copy",
            ]
            output_muxer = LocalChapterService._output_muxer(tmp_output)
            if output_muxer:
                command.extend(["-f", output_muxer])
            command.append(str(tmp_output))
            LocalChapterService._run_ffmpeg(command)
            os.replace(tmp_output, input_path)
        finally:
            try:
                os.unlink(metadata_path)
            except Exception:
                pass
            try:
                if tmp_output.exists():
                    tmp_output.unlink()
            except Exception:
                pass

    @staticmethod
    def write_grouped_file_titles(
        file_paths: List[str],
        chapter_titles: List[str],
        create_backup: bool = False,
    ):
        if len(file_paths) != len(chapter_titles):
            raise ValueError("File and title counts must match for grouped multi-file title write")

        for file_path, title in zip(file_paths, chapter_titles):
            input_path = Path(file_path)
            if not input_path.exists() or not input_path.is_file():
                raise FileNotFoundError(f"File not found: {input_path}")

            if create_backup:
                LocalChapterService._create_backup(input_path)

            tmp_output = input_path.with_name(f"{input_path.stem}.achew.tmp{input_path.suffix}")
            try:
                command = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(input_path),
                    "-map",
                    "0:a",
                    "-map",
                    "0:v?",
                    "-map_metadata",
                    "0",
                    "-c",
                    "copy",
                    "-metadata",
                    f"title={(title or '').replace(chr(10), ' ').strip()}",
                ]
                output_muxer = LocalChapterService._output_muxer(tmp_output)
                if output_muxer:
                    command.extend(["-f", output_muxer])
                command.append(str(tmp_output))
                LocalChapterService._run_ffmpeg(command)
                os.replace(tmp_output, input_path)
            finally:
                try:
                    if tmp_output.exists():
                        tmp_output.unlink()
                except Exception:
                    pass
