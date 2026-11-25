"""Application kernel tests.

Every test runs commands against a real SQLite file and asserts on what the
kernel then reports: the list, the open document, revisions, the notification
and what a reopened store holds. Nothing is mocked.
"""

from __future__ import annotations

import random
import sqlite3

import pytest

from core_ultra.kernel import ApplicationState, Kernel, KernelError, Revision, Sort

TITLES = ("Quarterly plan", "Café résumé — août", "Żółć gęślą jaźń")
BODY = "Première ligne: déjà vu, garçon.\nZweite Zeile: Größe, Übermut, Äpfel.\n\nCuarta línea: ¿mañana? ¡Sí!"


@pytest.fixture
def path(tmp_path):
    return tmp_path / "application.sqlite"


@pytest.fixture
def kernel(path):
    kernel = Kernel(path)
    for title in TITLES:
        kernel.create_document(title)
    yield kernel
    kernel.close()


def titles(kernel) -> list[str]:
    return [document.title for document in kernel.list_documents()]


def everything(kernel) -> tuple:
    """All the kernel reports: its state, and every listed document's revisions."""
    state = kernel.state()
    return state, {document.id: kernel.revisions(document.id) for document in state.documents}


def documents(kernel) -> dict:
    """Every listed document with its draft and its revisions, whatever the order."""
    return {document.id: (document, kernel.revisions(document.id)) for document in kernel.list_documents()}


# --- the commands -----------------------------------------------------------


def test_create_commits_a_document_at_revision_one(kernel):
    document = kernel.create_document("Ångström notes", "First line")
    assert (document.id, document.title, document.body, document.revision, document.draft) == (
        4,
        "Ångström notes",
        "First line",
        1,
        None,
    )
    assert titles(kernel) == [*TITLES, "Ångström notes"]
    assert kernel.revisions(4) == (Revision(4, 1, "Ångström notes", "First line"),)
    assert kernel.state().notification == "Created “Ångström notes”"


def test_open_makes_a_document_the_one_edit_and_save_act_on(kernel):
    assert kernel.state().open_document is None
    with pytest.raises(KernelError, match="no document is open"):
        kernel.edit("text")

    kernel.open_document(2)
    assert kernel.state().open_document.title == "Café résumé — août"
    kernel.edit(BODY)
    kernel.open_document(3)
    kernel.edit("Other text")
    assert kernel.document(2).draft == BODY
    assert kernel.document(3).draft == "Other text"


def test_edit_changes_the_draft_and_save_commits_it_as_the_next_revision(kernel):
    kernel.open_document(2)
    edited = kernel.edit(BODY)
    assert (edited.body, edited.draft, edited.text, edited.unsaved, edited.revision) == ("", BODY, BODY, True, 1)
    assert kernel.revisions(2) == (Revision(2, 1, "Café résumé — août", ""),)
    assert kernel.state().notification is None

    saved = kernel.save()
    assert (saved.body, saved.draft, saved.unsaved, saved.revision) == (BODY, None, False, 2)
    assert kernel.revisions(2) == (
        Revision(2, 1, "Café résumé — août", ""),
        Revision(2, 2, "Café résumé — août", BODY),
    )
    assert kernel.state().notification == "Saved “Café résumé — août”, revision 2"


def test_editing_back_to_the_committed_body_leaves_nothing_unsaved(kernel):
    kernel.open_document(1)
    kernel.edit("A draft")
    assert kernel.edit("").unsaved is False
    with pytest.raises(KernelError, match="nothing unsaved"):
        kernel.save()


def test_rename_commits_the_new_title_as_the_next_revision(kernel):
    kernel.open_document(1)
    kernel.edit("An unsaved draft")
    renamed = kernel.rename_document(1, "Plan trimestriel")
    assert (renamed.title, renamed.revision, renamed.body, renamed.draft) == ("Plan trimestriel", 2, "", "An unsaved draft")
    assert kernel.revisions(1) == (Revision(1, 1, "Quarterly plan", ""), Revision(1, 2, "Plan trimestriel", ""))
    assert titles(kernel) == ["Plan trimestriel", *TITLES[1:]]
    assert kernel.state().notification == "Renamed “Quarterly plan” to “Plan trimestriel”"


def test_sort_orders_the_list_by_creation_title_or_last_change(kernel):
    for title in ("éclair recipe", "Eagle survey", "fjord office"):
        kernel.create_document(title)
    created = [*TITLES, "éclair recipe", "Eagle survey", "fjord office"]
    assert titles(kernel) == created

    kernel.sort_documents("created", descending=True)
    assert titles(kernel) == created[::-1]

    # Without case, and with é beside e. A letter Unicode cannot take the
    # accent from, such as Ż, sorts after z.
    by_title = ["Café résumé — août", "Eagle survey", "éclair recipe", "fjord office", "Quarterly plan", "Żółć gęślą jaźń"]
    kernel.sort_documents("title")
    assert titles(kernel) == by_title
    kernel.sort_documents("title", descending=True)
    assert titles(kernel) == by_title[::-1]

    kernel.rename_document(2, "Café résumé — septembre")
    kernel.open_document(5)
    kernel.edit("Counted")
    kernel.sort_documents("modified", descending=True)
    assert titles(kernel)[:2] == ["Café résumé — septembre", "fjord office"]  # an unsaved edit is not a change
    kernel.save()
    assert titles(kernel)[:2] == ["Eagle survey", "Café résumé — septembre"]
    assert kernel.state().sort == Sort("modified", True)


def test_filter_lists_the_documents_whose_title_contains_the_text(kernel):
    kernel.filter_documents("RESUME")
    assert titles(kernel) == ["Café résumé — août"]
    kernel.filter_documents("Ź")
    assert titles(kernel) == ["Żółć gęślą jaźń"]  # "Ź" folds to "z", as "Ż" and "ź" do
    kernel.filter_documents("É")
    assert titles(kernel) == list(TITLES)  # every title holds an e, accented or not
    kernel.filter_documents("pl")
    assert titles(kernel) == ["Quarterly plan"]
    kernel.filter_documents("nothing like it")
    state = kernel.state()
    assert (state.documents, state.total_documents, state.filter) == ((), 3, "nothing like it")
    kernel.filter_documents("")
    assert titles(kernel) == list(TITLES)


def test_a_filtered_out_document_stays_open(kernel):
    kernel.open_document(1)
    kernel.filter_documents("café")
    state = kernel.state()
    assert [document.id for document in state.documents] == [2]
    assert state.open_document.id == 1


# --- undo -------------------------------------------------------------------


def test_undo_reverses_create_rename_edit_and_save_most_recent_first(kernel):
    snapshots = [documents(kernel)]
    kernel.create_document("A fourth document")
    snapshots.append(documents(kernel))
    kernel.open_document(4)
    kernel.rename_document(4, "Le quatrième")
    snapshots.append(documents(kernel))
    kernel.edit("Its first draft")
    snapshots.append(documents(kernel))
    kernel.save()
    assert kernel.document(4).revision == 3
    assert kernel.state().undoable == "save"

    for command in ("save", "edit", "rename", "create"):
        assert kernel.undo() == command
        assert kernel.state().notification == f"Undid {command}"
        assert documents(kernel) == snapshots.pop()

    state = kernel.state()
    assert (state.total_documents, state.open_document, state.undoable) == (3, None, "create")


def test_undoing_a_save_brings_back_the_draft_and_removes_its_revision(kernel):
    kernel.open_document(2)
    kernel.edit(BODY)
    kernel.save()
    kernel.undo()
    document = kernel.document(2)
    assert (document.body, document.draft, document.revision) == ("", BODY, 1)
    assert len(kernel.revisions(2)) == 1


def test_undo_with_nothing_to_undo_is_refused(path):
    kernel = Kernel(path)
    assert kernel.state().undoable is None
    with pytest.raises(KernelError, match="nothing to undo"):
        kernel.undo()
    kernel.create_document("Only one")
    kernel.undo()
    with pytest.raises(KernelError, match="nothing to undo"):
        kernel.undo()


def test_open_sort_and_filter_are_not_undone(kernel):
    kernel.open_document(3)
    kernel.sort_documents("title")
    kernel.filter_documents("a")
    assert kernel.undo() == "create"
    state = kernel.state()
    assert (state.sort, state.filter, state.open_document) == (Sort("title"), "a", None)  # document 3 is gone
    assert state.total_documents == 2


def test_an_identity_is_never_reused_after_a_create_is_undone(kernel):
    kernel.undo()
    assert kernel.create_document("Another third").id == 4


def test_undo_is_the_exact_inverse_over_a_long_scripted_session(path):
    """Two hundred commands chosen by a seeded generator, then every one undone:
    after each undo the documents, drafts and revisions are what they were
    before the command it reversed."""
    kernel = Kernel(path)
    chooser = random.Random(5)
    words = ("plan", "résumé", "fjord", "Żółć", "notes", "août", "Århus", "garçon")
    snapshots, ran = [], []
    while len(ran) < 200:
        state = kernel.state()
        command = chooser.choice(("create", "open", "rename", "edit", "save", "sort"))
        text = " ".join(chooser.sample(words, 3))
        before = documents(kernel)
        try:
            if command == "create":
                kernel.create_document(text)
            elif command == "open":
                kernel.open_document(chooser.randint(1, max(state.total_documents, 1)))
            elif command == "rename":
                kernel.rename_document(chooser.randint(1, max(state.total_documents, 1)), text)
            elif command == "edit":
                kernel.edit(chooser.choice((text, f"{text}\n{text}", "")))
            elif command == "save":
                kernel.save()
            else:
                kernel.sort_documents(chooser.choice(("created", "title", "modified")), chooser.random() < 0.5)
        except KernelError:
            assert documents(kernel) == before
            continue
        ran.append(command)
        if command not in ("open", "sort"):
            snapshots.append((command, before))

    assert set(ran) == {"create", "open", "rename", "edit", "save", "sort"}
    while snapshots:
        command, before = snapshots.pop()
        assert kernel.undo() == command
        assert documents(kernel) == before
    assert kernel.state().total_documents == 0
    kernel.close()


# --- validation -------------------------------------------------------------


REFUSED = {
    "a blank title": lambda k: k.create_document("   "),
    "an empty title": lambda k: k.create_document(""),
    "a title of two lines": lambda k: k.create_document("two\nlines"),
    "a title with a line separator": lambda k: k.create_document("two lines"),
    "a title that is not text": lambda k: k.create_document(7),
    "a body with a control character": lambda k: k.create_document("Title", "tab\there"),
    "a body that is not text": lambda k: k.create_document("Title", None),
    "opening a document that does not exist": lambda k: k.open_document(99),
    "opening by something that is not an id": lambda k: k.open_document("2"),
    "renaming a document that does not exist": lambda k: k.rename_document(99, "Title"),
    "renaming to a blank title": lambda k: k.rename_document(1, " "),
    "renaming to the same title": lambda k: k.rename_document(1, "Quarterly plan"),
    "an edit that changes nothing": lambda k: k.edit("Draft of the second"),
    "an edit with a carriage return": lambda k: k.edit("one\r\ntwo"),
    "a sort key that does not exist": lambda k: k.sort_documents("size"),
    "a sort direction that is not true or false": lambda k: k.sort_documents("title", "down"),
    "a filter of two lines": lambda k: k.filter_documents("a\nb"),
    "a filter that is not text": lambda k: k.filter_documents(None),
    "revisions of a document that does not exist": lambda k: k.revisions(99),
    "a binding without a command": lambda k: k.execute({"document": 1}),
    "a binding for an unknown command": lambda k: k.execute({"command": "delete", "document": 1}),
    "a binding without its document": lambda k: k.execute({"command": "open"}),
    "a rename binding without text": lambda k: k.execute({"command": "rename", "document": 1}),
    "an edit binding for a document that is not open": lambda k: k.execute({"command": "edit", "document": 1}, "text"),
}


@pytest.mark.parametrize("case", REFUSED)
def test_a_refused_command_changes_nothing(kernel, case):
    kernel.open_document(2)
    kernel.edit("Draft of the second")
    before = everything(kernel)
    with pytest.raises(KernelError):
        REFUSED[case](kernel)
    assert everything(kernel) == before


def test_save_with_nothing_unsaved_is_refused(kernel):
    with pytest.raises(KernelError, match="no document is open"):
        kernel.save()
    kernel.open_document(1)
    before = everything(kernel)
    with pytest.raises(KernelError, match="nothing unsaved"):
        kernel.save()
    assert everything(kernel) == before


# --- the store --------------------------------------------------------------


def test_state_survives_closing_and_reopening_the_store(path, kernel):
    kernel.open_document(2)
    kernel.edit(BODY)
    kernel.save()
    kernel.rename_document(3, "Żółć, wydanie drugie")
    kernel.edit(BODY + "\nUne ligne non enregistrée.")
    kernel.sort_documents("title", descending=True)
    kernel.filter_documents("é")
    kernel.create_document("Été à Århus")
    before = everything(kernel)
    state = before[0]
    assert state.open_document.unsaved and state.notification and state.undoable == "create"
    kernel.close()

    assert path.read_bytes().startswith(b"SQLite format 3\x00")
    reopened = Kernel(path)
    assert everything(reopened) == before

    # The undo log is in the store too: the reopened kernel undoes back to the
    # three untouched documents.
    for command in ("create", "edit", "rename", "save", "edit"):
        assert reopened.undo() == command
    reopened.filter_documents("")
    reopened.sort_documents("created")
    assert [(d.title, d.body, d.draft, d.revision) for d in reopened.list_documents()] == [
        (title, "", None, 1) for title in TITLES
    ]
    reopened.close()


def test_the_same_commands_give_the_same_state_in_any_store(tmp_path):
    states = []
    for name in ("one.sqlite", "two.sqlite"):
        kernel = Kernel(tmp_path / name)
        for title in TITLES:
            kernel.create_document(title)
        kernel.open_document(1)
        kernel.edit(BODY)
        kernel.save()
        kernel.sort_documents("modified", descending=True)
        states.append(everything(kernel))
        kernel.close()
    assert states[0] == states[1]
    assert isinstance(states[0][0], ApplicationState)


def test_a_store_written_by_the_first_kernel_is_read(path):
    """Schema version 1 held created documents only. They arrive unchanged, at revision 1."""
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE documents (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, "
        "body TEXT NOT NULL, revision INTEGER NOT NULL)"
    )
    old.executemany("INSERT INTO documents (title, body, revision) VALUES (?, '', 1)", [(title,) for title in TITLES])
    old.execute("PRAGMA user_version = 1")
    old.commit()
    old.close()

    kernel = Kernel(path)
    assert titles(kernel) == list(TITLES)
    assert kernel.revisions(2) == (Revision(2, 1, "Café résumé — août", ""),)
    kernel.rename_document(2, "Café résumé — septembre")
    kernel.sort_documents("modified", descending=True)
    assert titles(kernel)[0] == "Café résumé — septembre"
    assert kernel.create_document("A fourth").id == 4
    kernel.close()

    again = Kernel(path)
    assert again.state().total_documents == 4
    again.close()


def test_a_store_from_a_later_kernel_is_refused(path):
    later = sqlite3.connect(path)
    later.execute("PRAGMA user_version = 99")
    later.commit()
    later.close()
    with pytest.raises(KernelError, match="schema version 99"):
        Kernel(path)


# --- bindings ---------------------------------------------------------------


def test_a_binding_runs_the_command_it_names(kernel):
    kernel.execute({"command": "create"}, "Été à Århus")
    kernel.execute({"command": "open", "document": 4})
    kernel.execute({"command": "rename", "document": 4}, "Hiver à Århus")
    kernel.execute({"command": "edit", "document": 4}, "Il neige.")
    kernel.execute({"command": "save"})
    kernel.execute({"command": "sort", "key": "title", "descending": True})
    kernel.execute({"command": "filter"}, "århus")
    state = kernel.state()
    assert [(d.title, d.body, d.revision) for d in state.documents] == [("Hiver à Århus", "Il neige.", 3)]
    assert (state.sort, state.filter, state.open_document.id) == (Sort("title", True), "århus", 4)

    kernel.execute({"command": "undo"})
    assert kernel.document(4).draft == "Il neige."
