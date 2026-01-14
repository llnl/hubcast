from abc import ABC, abstractmethod
from typing import Union


class AccountMap(ABC):
    """
    An abstract interface defining an account map.
    """

    # while not all implementations will need to be async,
    # we allow for flexibility in the case that account maps
    # may need to make network calls (ie the oauth map)
    @abstractmethod
    async def __call__(self, github_user: dict) -> Union[str, None]:
        """
        Return the corresponding gitlab_user for a given github_user if
        one exists.

        Attributes:
        ----------
        github_user: dict
            The GitHub user information from the webhook event.
            Contains `login` (username) and `id` (numerical user ID).
        """
        pass
