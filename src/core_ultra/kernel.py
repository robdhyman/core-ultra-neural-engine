"""The application kernel: the conventional program that holds the truth.

Documents live in SQLite. Only two of the spec's commands exist so far, create
and list; open, rename, edit, save, sort/filter and undo are added by the issue
that builds the full document workspace.

`Kernel.state()` returns the committed application state the documents app
adapter describes. Nothing in it is a coordinate or a style value.
"""

from __future__ import annotations

import sqlite3
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType

SCHEMA_VERSION = 1


class KernelError(Exception):
    """A command the kernel refused, or a database it cannot read."""


@dataclass(frozen=True)
class Document:
    id: int
    title: str
    body: str
    revision: int


@dataclass(frozen=True)
class ApplicationState:
    """What the application knows at one moment.

    `documents` is committed state read from SQLite, in creation order.
    `interaction` is the pointer and focus state the running application holds
    in memory: a bound element's identity mapped to its current state. An
    element that is not named is in the default state.
    """

    documents: tuple[Document, ...]
    interaction: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def with_interaction(self, interaction: Mapping[str, str]) -> ApplicationState:
        return replace(self, interaction=MappingProxyType(dict(interaction)))


class Kernel:
    """Documents and the commands that change them, stored in one SQLite file."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._db = sqlite3.connect(str(path))
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            with self._db:
                self._db.execute(
                    "CREATE TABLE IF NOT EXISTS documents ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "title TEXT NOT NULL, "
                    "body TEXT NOT NULL, "
                    "revision INTEGER NOT NULL)"
                )
                self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        elif version != SCHEMA_VERSION:
            self._db.close()
            raise KernelError(
                f"the database is at schema version {version}; this kernel reads version {SCHEMA_VERSION}"
            )

    def create_document(self, title: str, body: str = "") -> Document:
        """Create a document and commit it. The title is stored exactly as given."""
        if not isinstance(title, str) or not isinstance(body, str):
            raise KernelError("a document's title and body are text")
        if not title.strip():
            raise KernelError("a document needs a title")
        if any(unicodedata.category(character) == "Cc" for character in title):
            raise KernelError("a document's title is a single line with no control characters")
        with self._db:
            cursor = self._db.execute(
                "INSERT INTO documents (title, body, revision) VALUES (?, ?, 1)", (title, body)
            )
        return Document(id=cursor.lastrowid, title=title, body=body, revision=1)

    def list_documents(self) -> tuple[Document, ...]:
        """Every committed document, in creation order."""
        rows = self._db.execute("SELECT id, title, body, revision FROM documents ORDER BY id")
        return tuple(Document(*row) for row in rows)

    def state(self) -> ApplicationState:
        """The committed application state, with every element in its default state."""
        return ApplicationState(documents=self.list_documents())

    def close(self) -> None:
        self._db.close()
