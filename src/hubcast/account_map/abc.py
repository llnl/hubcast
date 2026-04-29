from abc import ABC, abstractmethod


class AccountMap(ABC):
    """
    An abstract interface defining an account map.
    Maps usernames from a source forge to a destination forge.
    """

    @abstractmethod
    def __call__(self, source_user: str) -> str | None:
        """
        Return the corresponding destination forge user for a given source forge user
        if one exists.
        """
        pass
