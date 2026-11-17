"""Keep the Rasa tracker scoped to one turn."""

from rasa.core.tracker_store import InMemoryTrackerStore
from rasa.shared.core.trackers import DialogueStateTracker


class TurnTrackerStore(InMemoryTrackerStore):
    """The action host owns workflow state, so Rasa has no tracker history to retain."""

    async def save(self, tracker: DialogueStateTracker) -> None:
        return None
