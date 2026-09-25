"""The folder where custom tools live, and reading and writing them."""

import shutil
from dataclasses import dataclass
from pathlib import Path

from nexus.tools.custom.manifest import NAME_PATTERN, ToolManifest
from nexus.tools.custom.script_tool import ScriptTool

CUSTOM_TOOLS_DIR = Path.home() / ".nexus" / "tools"
SCRIPT_FILE = "run.py"
MANIFEST_FILE = "tool.json"


@dataclass(frozen=True)
class LoadedTools:
    """The custom tools found on disk, and a note about each folder that could not be used."""

    tools: list[ScriptTool]
    problems: list[str]


class ToolLibrary:
    """One folder per tool, each holding `tool.json` and `run.py`.

    The folder is readable only by its owner: it holds code that Nexus will run.
    """

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory

    @property
    def directory(self) -> Path:
        # Looked up on each use, so tests can point the default somewhere safe.
        return self._directory if self._directory is not None else CUSTOM_TOOLS_DIR

    def script_path(self, name: str) -> Path:
        """Where the script of tool `name` is (or would be)."""
        return self._folder(name) / SCRIPT_FILE

    def read_script(self, name: str) -> str | None:
        """The current code of tool `name`, or None if there is no such tool."""
        try:
            return self.script_path(name).read_text(encoding="utf-8")
        except (OSError, ValueError):
            return None

    def load_all(self) -> LoadedTools:
        """Read every tool folder. A broken one is skipped and reported, never fatal."""
        tools: list[ScriptTool] = []
        problems: list[str] = []
        folders = sorted(self.directory.iterdir()) if self.directory.is_dir() else []
        for folder in folders:
            if not folder.is_dir():
                continue
            try:
                tools.append(self._load(folder))
            except (OSError, ValueError) as err:
                problems.append(f"{folder.name}: {err}")
        return LoadedTools(tools, problems)

    def save(self, manifest: ToolManifest, code: str) -> ScriptTool:
        """Write a tool, replacing one with the same name. Raises OSError if it cannot."""
        folder = self._folder(manifest.name)
        folder.mkdir(parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        folder.chmod(0o700)
        # The script goes first: a folder without a manifest is ignored, so a crash between
        # the two writes never leaves a tool that half exists.
        _write(folder / SCRIPT_FILE, code)
        _write(folder / MANIFEST_FILE, manifest.to_json())
        return ScriptTool(manifest, folder / SCRIPT_FILE)

    def remove(self, name: str) -> bool:
        """Delete a tool's folder. Returns False if there was nothing to delete."""
        try:
            folder = self._folder(name)
        except ValueError:
            return False
        if not folder.is_dir():
            return False
        shutil.rmtree(folder)
        return True

    def _folder(self, name: str) -> Path:
        # The pattern allows no slash or dot, so a name can never point outside the library.
        if not NAME_PATTERN.fullmatch(name):
            raise ValueError(f"'{name}' is not a valid tool name")
        return self.directory / name

    def _load(self, folder: Path) -> ScriptTool:
        manifest = ToolManifest.from_json((folder / MANIFEST_FILE).read_text(encoding="utf-8"))
        if manifest.name != folder.name:
            raise ValueError(f"the folder is named {folder.name} but the tool is {manifest.name}")
        script = folder / SCRIPT_FILE
        if not script.is_file():
            raise ValueError(f"{SCRIPT_FILE} is missing")
        return ScriptTool(manifest, script)


def _write(path: Path, text: str) -> None:
    """Write through a temporary file so a reader never sees half of it."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)
