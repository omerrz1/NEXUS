"""What a custom tool is: its name, its purpose, and its inputs. Saved next to its script."""

import json
import re
from dataclasses import dataclass

from pydantic import BaseModel

NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]{2,39}")
PARAMETER_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,29}")
MAX_DESCRIPTION_CHARS = 200
MAX_PARAMETERS = 6


@dataclass(frozen=True)
class ToolManifest:
    """A custom tool's description. Every input is text, and every input is required.

    Building one checks it, so an invalid manifest cannot exist: a bad name or input raises
    ValueError with a message the model can act on.
    """

    name: str
    description: str
    parameters: dict[str, str]  # Input name -> what it means.

    def __post_init__(self) -> None:
        if not NAME_PATTERN.fullmatch(self.name):
            raise ValueError(
                f"the name '{self.name}' is not allowed: use 3 to 40 lowercase letters, "
                "digits, or underscores, starting with a letter (for example word_count)"
            )
        if not self.description.strip() or len(self.description) > MAX_DESCRIPTION_CHARS:
            raise ValueError(f"the description must be 1 to {MAX_DESCRIPTION_CHARS} characters")
        if len(self.parameters) > MAX_PARAMETERS:
            raise ValueError(f"a tool can have at most {MAX_PARAMETERS} inputs")
        for name, meaning in self.parameters.items():
            if not PARAMETER_PATTERN.fullmatch(name):
                raise ValueError(
                    f"the input name '{name}' is not allowed: use lowercase letters, digits, "
                    "or underscores, starting with a letter"
                )
            if hasattr(BaseModel, name) or name.startswith("model_"):
                raise ValueError(f"the input name '{name}' is reserved: pick another one")
            if not meaning.strip() or len(meaning) > MAX_DESCRIPTION_CHARS:
                raise ValueError(f"the meaning of input '{name}' must be 1 to 200 characters")

    def to_json(self) -> str:
        """The text saved in tool.json."""
        data = {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
        return json.dumps(data, indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "ToolManifest":
        """Read a saved manifest. Raises ValueError if it is damaged or invalid."""
        try:
            data = json.loads(text)
            parameters = data.get("parameters", {})
            if not isinstance(parameters, dict):
                raise ValueError("'parameters' must be an object")
            return cls(
                name=str(data["name"]),
                description=str(data["description"]),
                parameters={str(key): str(value) for key, value in parameters.items()},
            )
        except (KeyError, AttributeError, TypeError) as err:
            raise ValueError(f"the manifest is incomplete ({err})") from err
        except json.JSONDecodeError as err:
            raise ValueError(f"the manifest is not valid JSON ({err.msg})") from err
