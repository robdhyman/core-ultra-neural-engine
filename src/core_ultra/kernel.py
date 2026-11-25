"""The application kernel: the conventional program that holds the truth.

Everything the documents app knows is in one SQLite file: the documents, every
revision of each, unsaved drafts, which document is open, how the list is
sorted and filtered, the notification, and the undo log. Closing the kernel and
opening the file again gives the same state.

Commands: create, open, rename, edit, save, list, sort, filter and undo. A
command either happens whole, in one transaction, or is refused with
`KernelError` and changes nothing.

- **Revisions.** A document starts at revision 1. Each rename and each save
  commits one more revision; `revisions` returns them all, oldest first.
- **Drafts.** `edit` changes the open document's draft, never its committed
  body. `save` commits the draft as the next revision.
- **Undo.** create, rename, edit and save can be undone, most recent first,
  without limit. Undo is the exact inverse: the document, its draft and its
  revisions are as they were before the command, so undoing a save or a rename
  removes the revision it committed. open, sort and filter change the view and
  are not undone.
- **Time.** There is no wall clock. `Document.modified` is a counter that
  rises with each committed change, so the same commands always give the same
  state.

`Kernel.state()` returns the application state the documents app adapter
describes. Nothing in it is a coordinate or a style value.
"""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

SCHEMA_VERSION = 2
SORT_KEYS = ("created", "title", "modified")
UNDOABLE = ("create", "rename", "edit", "save")


class KernelError(Exception):
    """A command the kernel refused, or a database it cannot read."""


@dataclass(frozen=True)
class Document:
    """One document. `body` is the committed text; `draft` is the unsaved text,
    or None when nothing is unsaved."""

    id: int
    title: str
    body: str
    revision: int
    draft: str | None = None
    modified: int = 0

    @property
    def text(self) -> str:
        """What the editor shows: the draft when there is one."""
        return self.body if self.draft is None else self.draft

    @property
    def unsaved(self) -> bool:
        return self.draft is not None


@dataclass(frozen=True)
class Revision:
    document: int
    revision: int
    title: str
    body: str


@dataclass(frozen=True)
class Sort:
    key: str = "created"
    descending: bool = False


@dataclass(frozen=True)
class ApplicationState:
    """What the application knows at one moment.

    `documents` is the list as the list command returns it: the filter applied,
    in the sort order. `total_documents` counts every document, listed or not.
    `undoable` names the command that undo would reverse, or is None.

    `interaction` is the pointer and focus state the running application holds
    in memory: a bound element's identity mapped to its current state. An
    element that is not named is in the default state. It is the one part of
    the state that is not stored.
    """

    documents: tuple[Document, ...]
    total_documents: int = 0
    sort: Sort = Sort()
    filter: str = ""
    open_document: Document | None = None
    undoable: str | None = None
    notification: str | None = None
    interaction: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def with_interaction(self, interaction: Mapping[str, str]) -> ApplicationState:
        return replace(self, interaction=MappingProxyType(dict(interaction)))


_DOCUMENT_COLUMNS = "id, title, body, revision, draft, modified"


class Kernel:
    """Documents and the commands that change them, stored in one SQLite file."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._db = sqlite3.connect(str(path))
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, SCHEMA_VERSION):
            self._db.close()
            raise KernelError(
                f"the database is at schema version {version}; this kernel reads version {SCHEMA_VERSION}"
            )
        if version != SCHEMA_VERSION:
            with self._db:
                self._db.execute("BEGIN")
                if version == 0:
                    self._db.execute(
                        "CREATE TABLE documents ("
                        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                        "title TEXT NOT NULL, "
                        "body TEXT NOT NULL, "
                        "revision INTEGER NOT NULL, "
                        "draft TEXT, "
                        "modified INTEGER NOT NULL DEFAULT 0)"
                    )
                else:
                    # Version 1 held created documents only, each at revision 1.
                    self._db.execute("ALTER TABLE documents ADD COLUMN draft TEXT")
                    self._db.execute("ALTER TABLE documents ADD COLUMN modified INTEGER NOT NULL DEFAULT 0")
                    self._db.execute("UPDATE documents SET modified = id")
                self._db.execute(
                    "CREATE TABLE revisions ("
                    "document INTEGER NOT NULL, "
                    "revision INTEGER NOT NULL, "
                    "title TEXT NOT NULL, "
                    "body TEXT NOT NULL, "
                    "PRIMARY KEY (document, revision))"
                )
                self._db.execute("INSERT INTO revisions SELECT id, revision, title, body FROM documents")
                self._db.execute(
                    "CREATE TABLE workspace ("
                    "id INTEGER PRIMARY KEY CHECK (id = 1), "
                    "open_document INTEGER, "
                    "sort_key TEXT NOT NULL, "
                    "sort_descending INTEGER NOT NULL, "
                    "filter TEXT NOT NULL, "
                    "notification TEXT, "
                    "clock INTEGER NOT NULL)"
                )
                self._db.execute(
                    "INSERT INTO workspace VALUES (1, NULL, 'created', 0, '', NULL, "
                    "(SELECT COALESCE(MAX(modified), 0) FROM documents))"
                )
                self._db.execute(
                    "CREATE TABLE undo_log ("
                    "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "command TEXT NOT NULL, "
                    "document INTEGER NOT NULL, "
                    "before TEXT NOT NULL)"
                )
                self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # --- commands -----------------------------------------------------------

    def create_document(self, title: str, body: str = "") -> Document:
        """Create a document at revision 1. The title is stored exactly as given."""
        _check_title(title)
        _check_body(body)
        with self._db:
            modified = self._tick()
            cursor = self._db.execute(
                "INSERT INTO documents (title, body, revision, modified) VALUES (?, ?, 1, ?)", (title, body, modified)
            )
            document_id = cursor.lastrowid
            self._db.execute("INSERT INTO revisions VALUES (?, 1, ?, ?)", (document_id, title, body))
            self._log("create", document_id, {})
            self._notify(f"Created “{title}”")
        return self.document(document_id)

    def open_document(self, document_id: int) -> Document:
        """Make this the open document, the one `edit` and `save` act on."""
        document = self.document(document_id)
        with self._db:
            self._db.execute("UPDATE workspace SET open_document = ?", (document.id,))
            self._notify(None)
        return document

    def rename_document(self, document_id: int, title: str) -> Document:
        """Give a document a new title, committed as its next revision."""
        document = self.document(document_id)
        _check_title(title)
        if title == document.title:
            raise KernelError("the document already has that title")
        with self._db:
            modified = self._tick()
            revision = document.revision + 1
            self._db.execute(
                "UPDATE documents SET title = ?, revision = ?, modified = ? WHERE id = ?",
                (title, revision, modified, document.id),
            )
            self._db.execute("INSERT INTO revisions VALUES (?, ?, ?, ?)", (document.id, revision, title, document.body))
            self._log("rename", document.id, {"title": document.title, "modified": document.modified})
            self._notify(f"Renamed “{document.title}” to “{title}”")
        return self.document(document.id)

    def edit(self, body: str) -> Document:
        """Change the open document's draft. Nothing is committed until `save`.

        A draft equal to the committed body is no draft: the document has
        nothing unsaved.
        """
        document = self._open()
        _check_body(body)
        if body == document.text:
            raise KernelError("the edit changes nothing")
        with self._db:
            draft = None if body == document.body else body
            self._db.execute("UPDATE documents SET draft = ? WHERE id = ?", (draft, document.id))
            self._log("edit", document.id, {"draft": document.draft})
            self._notify(None)
        return self.document(document.id)

    def save(self) -> Document:
        """Commit the open document's draft as its next revision."""
        document = self._open()
        if document.draft is None:
            raise KernelError("the open document has nothing unsaved")
        with self._db:
            modified = self._tick()
            revision = document.revision + 1
            self._db.execute(
                "UPDATE documents SET body = ?, draft = NULL, revision = ?, modified = ? WHERE id = ?",
                (document.draft, revision, modified, document.id),
            )
            self._db.execute(
                "INSERT INTO revisions VALUES (?, ?, ?, ?)", (document.id, revision, document.title, document.draft)
            )
            self._log(
                "save", document.id, {"body": document.body, "draft": document.draft, "modified": document.modified}
            )
            self._notify(f"Saved “{document.title}”, revision {revision}")
        return self.document(document.id)

    def list_documents(self) -> tuple[Document, ...]:
        """The documents whose titles match the filter, in the sort order."""
        _, sort, filter_text, _ = self._workspace()
        rows = self._db.execute(f"SELECT {_DOCUMENT_COLUMNS} FROM documents ORDER BY id")
        documents = [Document(*row) for row in rows]
        if filter_text:
            needle = _fold(filter_text)
            documents = [document for document in documents if needle in _fold(document.title)]
        keys = {
            "created": lambda document: document.id,
            "title": lambda document: (_fold(document.title), document.title, document.id),
            "modified": lambda document: (document.modified, document.id),
        }
        return tuple(sorted(documents, key=keys[sort.key], reverse=sort.descending))

    def sort_documents(self, key: str, descending: bool = False) -> None:
        """Set the order of the list: by creation, by title or by last committed change.

        Titles are compared without case and without the accents that Unicode
        can separate from their letters.
        """
        if key not in SORT_KEYS:
            raise KernelError(f"{key!r} is not a sort key; the keys are {', '.join(SORT_KEYS)}")
        if not isinstance(descending, bool):
            raise KernelError("descending is true or false")
        with self._db:
            self._db.execute("UPDATE workspace SET sort_key = ?, sort_descending = ?", (key, int(descending)))
            self._notify(None)

    def filter_documents(self, text: str) -> None:
        """List only documents whose title contains this text; empty text lists all.

        Matching ignores case and the accents that Unicode can separate from
        their letters.
        """
        if not isinstance(text, str):
            raise KernelError("a filter is text")
        if _has_line_break_or_control(text):
            raise KernelError("a filter is a single line with no control characters")
        with self._db:
            self._db.execute("UPDATE workspace SET filter = ?", (text,))
            self._notify(None)

    def undo(self) -> str:
        """Reverse the most recent create, rename, edit or save. Returns its name."""
        entry = self._db.execute(
            "SELECT sequence, command, document, before FROM undo_log ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        if entry is None:
            raise KernelError("there is nothing to undo")
        sequence, command, document_id, before = entry
        before = json.loads(before)
        with self._db:
            if command == "create":
                self._db.execute("DELETE FROM revisions WHERE document = ?", (document_id,))
                self._db.execute("DELETE FROM documents WHERE id = ?", (document_id,))
                self._db.execute(
                    "UPDATE workspace SET open_document = NULL WHERE open_document = ?", (document_id,)
                )
            elif command == "edit":
                self._db.execute("UPDATE documents SET draft = ? WHERE id = ?", (before["draft"], document_id))
            else:
                self._db.execute(
                    "DELETE FROM revisions WHERE document = ? AND revision = "
                    "(SELECT revision FROM documents WHERE id = ?)",
                    (document_id, document_id),
                )
                if command == "rename":
                    self._db.execute(
                        "UPDATE documents SET title = ?, revision = revision - 1, modified = ? WHERE id = ?",
                        (before["title"], before["modified"], document_id),
                    )
                else:
                    self._db.execute(
                        "UPDATE documents SET body = ?, draft = ?, revision = revision - 1, modified = ? WHERE id = ?",
                        (before["body"], before["draft"], before["modified"], document_id),
                    )
            self._db.execute("DELETE FROM undo_log WHERE sequence = ?", (sequence,))
            self._notify(f"Undid {command}")
        return command

    def execute(self, binding: Mapping[str, Any], text: str | None = None) -> None:
        """Run the command a bound element's action binding names.

        `text` is what the person typed, for the commands that take text:
        create (the title), rename (the title), edit (the body) and filter.
        """
        if not isinstance(binding, Mapping) or "command" not in binding:
            raise KernelError("a binding names a command")
        command = binding["command"]
        if command in ("create", "rename", "edit", "filter") and text is None:
            raise KernelError(f"{command} needs text")
        try:
            if command == "create":
                self.create_document(text)
            elif command == "open":
                self.open_document(binding["document"])
            elif command == "rename":
                self.rename_document(binding["document"], text)
            elif command == "edit":
                if binding["document"] != self._workspace()[0]:
                    raise KernelError("the binding edits a document that is not open")
                self.edit(text)
            elif command == "save":
                self.save()
            elif command == "sort":
                self.sort_documents(binding["key"], binding["descending"])
            elif command == "filter":
                self.filter_documents(text)
            elif command == "undo":
                self.undo()
            else:
                raise KernelError(f"{command!r} is not a command")
        except KeyError as missing:
            raise KernelError(f"the {command} binding has no {missing.args[0]}") from None

    # --- queries ------------------------------------------------------------

    def document(self, document_id: int) -> Document:
        row = None
        if isinstance(document_id, int) and not isinstance(document_id, bool):
            row = self._db.execute(f"SELECT {_DOCUMENT_COLUMNS} FROM documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            raise KernelError(f"there is no document {document_id!r}")
        return Document(*row)

    def revisions(self, document_id: int) -> tuple[Revision, ...]:
        """Every committed revision of a document, oldest first."""
        document = self.document(document_id)
        rows = self._db.execute(
            "SELECT document, revision, title, body FROM revisions WHERE document = ? ORDER BY revision", (document.id,)
        )
        return tuple(Revision(*row) for row in rows)

    def state(self) -> ApplicationState:
        """The application state, with every element in its default interaction state."""
        open_id, sort, filter_text, notification = self._workspace()
        last = self._db.execute("SELECT command FROM undo_log ORDER BY sequence DESC LIMIT 1").fetchone()
        return ApplicationState(
            documents=self.list_documents(),
            total_documents=self._db.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            sort=sort,
            filter=filter_text,
            open_document=None if open_id is None else self.document(open_id),
            undoable=None if last is None else last[0],
            notification=notification,
        )

    def close(self) -> None:
        self._db.close()

    # --- inside a command ---------------------------------------------------

    def _workspace(self) -> tuple[int | None, Sort, str, str | None]:
        open_id, key, descending, filter_text, notification = self._db.execute(
            "SELECT open_document, sort_key, sort_descending, filter, notification FROM workspace"
        ).fetchone()
        return open_id, Sort(key, bool(descending)), filter_text, notification

    def _open(self) -> Document:
        open_id = self._workspace()[0]
        if open_id is None:
            raise KernelError("no document is open")
        return self.document(open_id)

    def _tick(self) -> int:
        self._db.execute("UPDATE workspace SET clock = clock + 1")
        return self._db.execute("SELECT clock FROM workspace").fetchone()[0]

    def _log(self, command: str, document_id: int, before: dict[str, Any]) -> None:
        self._db.execute(
            "INSERT INTO undo_log (command, document, before) VALUES (?, ?, ?)",
            (command, document_id, json.dumps(before, ensure_ascii=False)),
        )

    def _notify(self, message: str | None) -> None:
        self._db.execute("UPDATE workspace SET notification = ?", (message,))


def _has_line_break_or_control(text: str, allow: str = "") -> bool:
    return any(
        character not in allow and unicodedata.category(character) in ("Cc", "Zl", "Zp") for character in text
    )


def _check_title(title: Any) -> None:
    if not isinstance(title, str):
        raise KernelError("a document's title is text")
    if not title.strip():
        raise KernelError("a document needs a title")
    if _has_line_break_or_control(title):
        raise KernelError("a document's title is a single line with no control characters")


def _check_body(body: Any) -> None:
    if not isinstance(body, str):
        raise KernelError("a document's body is text")
    if _has_line_break_or_control(body, allow="\n"):
        raise KernelError("a document's body holds no control characters; its lines end with a line feed")


def _fold(text: str) -> str:
    """Text for comparing: no case, and no accent that Unicode can separate from its letter."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(character for character in decomposed if not unicodedata.combining(character)).casefold()
