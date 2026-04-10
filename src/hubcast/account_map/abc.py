from abc import ABC, abstractmethod


class AccountMap(ABC):
    """
    An abstract interface defining an account map.
    """

    @abstractmethod
    def __call__(self, github_user: str) -> str | None:
        """
        Return the coorisponding gitlab_user for a given github_user if
        one exists.
        """
        pass
