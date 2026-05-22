import yaml

from .abc import AccountMap


class FileMapError(Exception):
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

    path: str
    users: dict[str, str]

    def __init__(self, path: str):
        """
        Constructor, path to read from and generate a simple account
        mapping between services.
        """
        self.path = path

        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)
                self.users = data["Users"]
                pass
        except FileNotFoundError:
            raise FileMapError(f"File map not found. path={path}")
        except yaml.YAMLError:
            raise FileMapError(f"Failed to parse file map. path={path}")

    def __call__(self, source_user: str) -> str | None:
        """
        Return the destination forge user for a source forge user if one exists.
        """
        return self.users.get(source_user)
