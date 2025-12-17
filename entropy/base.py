"""Base class for entropy sources."""

from abc import ABC, abstractmethod


class EntropySource(ABC):
    """Abstract base class for entropy sources."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this entropy source."""
        pass

    @abstractmethod
    def collect(self) -> bytes:
        """Collect entropy from this source."""
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.name}>"
