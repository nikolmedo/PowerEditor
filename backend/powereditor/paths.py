import os
from dataclasses import dataclass
from pathlib import Path

import platformdirs

ENV_DATA_DIR = "POWEREDITOR_DATA_DIR"
APP_NAME = "PowerEditor"


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path

    @classmethod
    def from_env(cls) -> "AppPaths":
        override = os.environ.get(ENV_DATA_DIR)
        if override:
            return cls(data_dir=Path(override))
        return cls(data_dir=Path(platformdirs.user_data_dir(APP_NAME, appauthor=False)))

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def bin_dir(self) -> Path:
        return self.data_dir / "bin"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def settings_file(self) -> Path:
        return self.data_dir / "settings.json"

    def ensure_dirs(self) -> None:
        for directory in (self.projects_dir, self.models_dir, self.bin_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)
