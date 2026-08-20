from pathlib import Path

import yaml

from hubcast.exceptions import HubcastError

from .abc import AccountMap


class FileMapError(HubcastError):
    pass


class FileMap(AccountMap):
    """
    A simple user map importing from a YAML file of the form.

    Users:
      github_user: gitlab_user
      github_user2: gitlab_user2

    Attributes
    ----------
    path: str
        A filepath to the users.yml defining a usermapping.
    """

    path: Path
    users: dict[str, str]

    def __init__(self, path: Path | str):
        """
        Constructor, path to read from and generate a simple account
        mapping between services.
        """
        self.path = Path(path)

        try:
            data = yaml.safe_load(self.path.read_text())
            self.users = data["Users"]
        except FileNotFoundError as e:
            raise FileMapError(f"File map not found. path={path}") from e
        except yaml.YAMLError as e:
            raise FileMapError(f"Failed to parse file map. path={path}") from e
        except (KeyError, TypeError) as e:
            raise FileMapError(f"File map missing Users section. path={path}") from e

    async def __call__(self, source_user: str) -> str | None:
        """
        Return the destination forge user for a source forge user if one exists.
        """
        return self.users.get(source_user)
