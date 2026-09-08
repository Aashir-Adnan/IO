from __future__ import annotations

from io_assistant.backend.interface import Backend
from io_assistant.models_domain import Intent


class Router:
    """Classifier that routes utterances to intents via a backend.

    Treats empty/whitespace utterances as "unknown" without calling the model.
    """

    def __init__(self, backend: Backend):
        self._backend = backend

    def classify(self, utterance: str, *, context: str | None = None) -> Intent:
        """Classify an utterance into an intent.

        Args:
            utterance: The user input to classify.

        Returns:
            The classified intent ("store", "query", or "unknown").
        """
        if not utterance or not utterance.strip():
            return "unknown"
        return self._backend.route(utterance, context=context)
