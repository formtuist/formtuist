"""Reviewer TUI for manual post-grading of responses."""

import sqlite3
from pathlib import Path
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Header, Input, Label, Static

from formtuist.database import get_responses, init_db, set_post_grade
from formtuist.grader import (
    BREAKDOWN_ID_KEY,
    BREAKDOWN_MAX_KEY,
    BREAKDOWN_SCORE_KEY,
    COMMENT_KEY,
    FINAL_SCORE_KEY,
    MANUAL_SCORE_KEY,
    NEEDS_REVIEW_KEY,
    REVIEWED_AT_KEY,
    REVIEWED_BY_KEY,
)
from formtuist.schema import (
    REVIEW_PERMITTED,
    REVIEW_REQUIRED,
    CodeBlock,
    FormDefinition,
    NumericRange,
    Question,
)
from formtuist.tui.widgets import (
    CODE_THEME_FALLBACK_DARK,
    FormtuistFooter,
    resolve_code_theme,
)

# labels for the review screen
REVIEW_SIDEBAR_TITLE = "[bold]Questions[/bold]"
REVIEW_PENDING_SUFFIX = " pending"
REVIEW_NO_QUESTIONS = "No reviewable questions."
REVIEW_NO_RESPONSES = "No responses for this question."
REVIEW_SCORE_LABEL = "Manual score"
REVIEW_COMMENT_LABEL = "Comment"
REVIEW_SAVE_LABEL = "Save"
REVIEW_QUIT_LABEL = "Quit"
REVIEW_ANSWER_LABEL = "Student answer: "
REVIEW_CORRECT_LABEL = "Expected: "
REVIEW_PATTERN_LABEL = "Pattern: "
REVIEW_PRELIM_LABEL = "Prelim: "
REVIEW_FINAL_LABEL = "Final: "
REVIEW_REVIEWED_LABEL = "Reviewed: "
REVIEW_QUESTION_COUNTER = "Q {cur} / {total} • R {rcur} / {rtotal}"

SIDEBAR_TITLE_MAX = 28


def _format_answer(value: Any) -> str:
    """Render an answer value for display in the review detail."""
    if value is None:
        return "(no answer)"
    if isinstance(value, CodeBlock):
        return value.content or ""
    if isinstance(value, NumericRange):
        return f"between {value.min:g} and {value.max:g}"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


class ReviewScreen(Screen):
    """Question-first reviewer screen for post-grading."""

    BINDINGS: ClassVar[
        list[Binding | tuple[str, str] | tuple[str, str, str]]
    ] = [
        Binding("ctrl+s", "save", "Save"),
        Binding("ctrl+j", "next_response", "Next R"),
        Binding("ctrl+k", "prev_response", "Prev R"),
        Binding("ctrl+n", "next_question", "Next Q"),
        Binding("ctrl+p", "prev_question", "Prev Q"),
        Binding("f", "toggle_pending", "Pending"),
        Binding("e", "focus_score", "Edit Score"),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(
        self,
        form: FormDefinition,
        db_path: Path,
        review_type: str = "required",
        question_filter: str | None = None,
        reviewer: str | None = None,
    ) -> None:
        """Store form, db path, and review filters."""
        self.form = form
        self.db_path = db_path
        self.review_type = review_type
        self.question_filter = question_filter
        self.reviewer = reviewer
        self.pending_only = False
        if review_type == "all":
            allowed = {REVIEW_REQUIRED, REVIEW_PERMITTED}
        else:
            allowed = {REVIEW_REQUIRED}
        all_reviewable = [q for q in form.questions if q.review in allowed]
        if question_filter is not None:
            all_reviewable = [
                q for q in all_reviewable if q.id == question_filter
            ]
        self.reviewable_questions: list[Question] = all_reviewable
        self.current_q = 0
        self.current_r = 0
        self.responses: list[dict[str, Any]] = []
        self.conn: sqlite3.Connection | None = None
        self.sidebar_items: list[Static] = []
        self.score_input: Input | None = None
        self.comment_input: Any = None
        super().__init__()

    def compose(self) -> ComposeResult:
        """Render the question-first reviewer layout."""
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static(REVIEW_SIDEBAR_TITLE, id="sidebar-title")
                if not self.reviewable_questions:
                    yield Static(REVIEW_NO_QUESTIONS)
                for question in self.reviewable_questions:
                    label = self._question_label(question)
                    item = Static(label, classes="sidebar-item")
                    self.sidebar_items.append(item)
                    yield item
            with VerticalScroll(id="review-detail"):
                yield Static("", id="review-question-title")
                yield Static("", id="review-question-text")
                yield Static("", id="review-code")
                yield Static("", id="review-answer")
                yield Static("", id="review-correct")
                yield Static("", id="review-pattern")
                yield Static("", id="review-prelim")
                yield Static("", id="review-final")
                yield Static("", id="review-reviewed")
                yield Label(REVIEW_SCORE_LABEL, id="review-score-label")
                score = Input(placeholder="0..points")
                score.id = "review-score"
                self.score_input = score
                yield score
                yield Label(REVIEW_COMMENT_LABEL, id="review-comment-label")
                from textual.widgets import TextArea  # noqa: PLC0415

                ta = TextArea()
                ta.id = "review-comment"
                self.comment_input = ta
                yield ta
                yield Static("", id="review-counter")
                yield Button(
                    REVIEW_SAVE_LABEL, id="review-save", variant="primary"
                )
                yield Button(
                    REVIEW_QUIT_LABEL, id="review-quit", variant="default"
                )
        yield FormtuistFooter()

    def on_mount(self) -> None:
        """Load responses and render the first question."""
        self.conn = init_db(self.db_path)
        self.responses = get_responses(self.conn, form_name=self.form.name)
        self._refresh_sidebar()
        self._render_detail()

    def on_unmount(self) -> None:
        """Close the database connection."""
        if self.conn is not None:
            self.conn.close()

    def _question_label(self, question: Question) -> str:
        """Return a truncated sidebar label with pending count."""
        pending = self._pending_for_question(question.id)
        text = question.text
        if len(text) > SIDEBAR_TITLE_MAX:
            text = text[: SIDEBAR_TITLE_MAX - 3] + "..."
        return f"{text} ({pending}{REVIEW_PENDING_SUFFIX})"

    def _pending_for_question(self, qid: str) -> int:
        """Count pending reviews for a question."""
        count = 0
        for resp in self.responses:
            grade = resp.get("grade_json")
            if grade is None:
                continue
            for entry in grade.get("breakdown", []):
                if entry.get(BREAKDOWN_ID_KEY) != qid:
                    continue
                if (
                    entry.get(NEEDS_REVIEW_KEY)
                    and entry.get(MANUAL_SCORE_KEY) is None
                ):
                    count += 1
        return count

    def _responses_for_question(self, qid: str) -> list[dict[str, Any]]:
        """Return responses that contain the given question."""
        result = []
        for resp in self.responses:
            grade = resp.get("grade_json")
            if grade is None:
                continue
            for entry in grade.get("breakdown", []):
                if entry.get(BREAKDOWN_ID_KEY) == qid:
                    result.append(resp)
                    break
        if self.pending_only:
            filtered = []
            for resp in result:
                grade = resp.get("grade_json")
                if grade is None:
                    continue
                for entry in grade.get("breakdown", []):
                    if entry.get(BREAKDOWN_ID_KEY) != qid:
                        continue
                    if (
                        entry.get(NEEDS_REVIEW_KEY)
                        and entry.get(MANUAL_SCORE_KEY) is None
                    ):
                        filtered.append(resp)
            return filtered
        return result

    def _refresh_sidebar(self) -> None:
        """Update the pending counts in the sidebar."""
        for idx, question in enumerate(self.reviewable_questions):
            label = self._question_label(question)
            if idx < len(self.sidebar_items):
                self.sidebar_items[idx].update(label)
                self.sidebar_items[idx].set_class(
                    idx == self.current_q, "current"
                )

    def _render_detail(self) -> None:  # noqa: PLR0912, PLR0915
        """Render the current question and response detail."""
        if not self.reviewable_questions:
            return
        question = self.reviewable_questions[self.current_q]
        rlist = self._responses_for_question(question.id)
        if self.current_r >= len(rlist):
            self.current_r = max(0, len(rlist) - 1)
        self._refresh_sidebar()
        try:
            title = self.query_one("#review-question-title", Static)
            title.update(f"[bold]{question.text}[/bold]")
            qtext = self.query_one("#review-question-text", Static)
            points = getattr(question, "points", 0)
            qtext.update(f"id: {question.id} • points: {points}")
            code_area = self.query_one("#review-code", Static)
            if question.code is not None:
                from rich.syntax import Syntax  # noqa: PLC0415

                theme = self._code_theme()
                syntax = Syntax(
                    (question.code.content or "").rstrip(),
                    question.code.language,
                    theme=theme,
                    line_numbers=True,
                )
                code_area.update(syntax)
            else:
                code_area.update("")
        except Exception:
            pass
        if not rlist:
            try:
                self.query_one("#review-answer", Static).update(
                    REVIEW_NO_RESPONSES
                )
                correct = getattr(question, "correct_answer", None)
                if correct is None:
                    correct_str = "(no expected answer)"
                else:
                    correct_str = _format_answer(correct)
                self.query_one("#review-correct", Static).update(
                    f"{REVIEW_CORRECT_LABEL}{correct_str}"
                )
                grading_type = getattr(question, "grading_type", None)
                accepts = getattr(question, "accepts", None)
                if grading_type == "regex":
                    pat = accepts
                    if pat is None and isinstance(correct, str):
                        pat = correct
                    pat_str = f"regex: {pat}" if pat else "(no pattern)"
                elif grading_type == "contains":
                    pat_str = (
                        f"contains: {_format_answer(correct)}"
                        if correct is not None
                        else "(none)"
                    )
                elif grading_type:
                    pat_str = (
                        f"{grading_type}: {_format_answer(correct)}"
                        if correct is not None
                        else f"{grading_type}"
                    )
                else:
                    pat_str = "(none)"
                self.query_one("#review-pattern", Static).update(
                    f"{REVIEW_PATTERN_LABEL}{pat_str}"
                )
                self.query_one("#review-prelim", Static).update("")
                self.query_one("#review-final", Static).update("")
                self.query_one("#review-reviewed", Static).update("")
                self.query_one("#review-counter", Static).update(
                    REVIEW_QUESTION_COUNTER.format(
                        cur=self.current_q + 1,
                        total=len(self.reviewable_questions),
                        rcur=0,
                        rtotal=0,
                    )
                )
            except Exception:
                pass
            if self.score_input is not None:
                self.score_input.value = ""
            return
        resp = rlist[self.current_r]
        grade = resp.get("grade_json")
        entry = None
        if grade is not None:
            for e in grade.get("breakdown", []):
                if e.get(BREAKDOWN_ID_KEY) == question.id:
                    entry = e
                    break
        answer = resp.get("answers_json", {}).get(question.id)
        try:
            self.query_one("#review-answer", Static).update(
                f"{REVIEW_ANSWER_LABEL}{_format_answer(answer)}"
            )
            # expected answer and pattern for the reviewer
            correct = getattr(question, "correct_answer", None)
            if correct is None:
                correct_str = "(no expected answer)"
            else:
                correct_str = _format_answer(correct)
            self.query_one("#review-correct", Static).update(
                f"{REVIEW_CORRECT_LABEL}{correct_str}"
            )
            grading_type = getattr(question, "grading_type", None)
            accepts = getattr(question, "accepts", None)
            if grading_type == "regex":
                pat = accepts
                if pat is None and isinstance(correct, str):
                    pat = correct
                pat_str = f"regex: {pat}" if pat else "(no pattern)"
            elif grading_type == "contains":
                pat_str = (
                    f"contains: {_format_answer(correct)}"
                    if correct is not None
                    else "(none)"
                )
            elif grading_type:
                pat_str = (
                    f"{grading_type}: {_format_answer(correct)}"
                    if correct is not None
                    else f"{grading_type}"
                )
            else:
                pat_str = "(none)"
            self.query_one("#review-pattern", Static).update(
                f"{REVIEW_PATTERN_LABEL}{pat_str}"
            )
            if entry is not None:
                prelim = entry.get(BREAKDOWN_SCORE_KEY)
                final = entry.get(FINAL_SCORE_KEY, prelim)
                max_pts = entry.get(BREAKDOWN_MAX_KEY)
                self.query_one("#review-prelim", Static).update(
                    f"{REVIEW_PRELIM_LABEL}{prelim} / {max_pts}"
                )
                self.query_one("#review-final", Static).update(
                    f"{REVIEW_FINAL_LABEL}{final} / {max_pts}"
                )
                reviewed = entry.get(REVIEWED_BY_KEY)
                at = entry.get(REVIEWED_AT_KEY)
                if reviewed:
                    self.query_one("#review-reviewed", Static).update(
                        f"{REVIEW_REVIEWED_LABEL}{reviewed} at {at}"
                    )
                else:
                    self.query_one("#review-reviewed", Static).update("")
                self.query_one("#review-counter", Static).update(
                    REVIEW_QUESTION_COUNTER.format(
                        cur=self.current_q + 1,
                        total=len(self.reviewable_questions),
                        rcur=self.current_r + 1,
                        rtotal=len(rlist),
                    )
                )
                if self.score_input is not None:
                    manual = entry.get(MANUAL_SCORE_KEY)
                    val = manual if manual is not None else final
                    self.score_input.value = (
                        str(val) if val is not None else ""
                    )
                comment = entry.get(COMMENT_KEY) or ""
                if self.comment_input is not None:
                    try:
                        self.comment_input.text = comment
                    except Exception:
                        pass
            else:
                self.query_one("#review-prelim", Static).update("")
                self.query_one("#review-final", Static).update("")
        except Exception:
            pass

    def _code_theme(self) -> str:
        """Return a Pygments theme matching the app."""
        try:
            return resolve_code_theme(self.app)
        except Exception:
            return CODE_THEME_FALLBACK_DARK

    def action_next_response(self) -> None:
        """Go to the next response for the current question."""
        if not self.reviewable_questions:
            return
        qid = self.reviewable_questions[self.current_q].id
        rlist = self._responses_for_question(qid)
        if not rlist:
            return
        self.current_r = (self.current_r + 1) % len(rlist)
        self._render_detail()

    def action_prev_response(self) -> None:
        """Go to the previous response for the current question."""
        if not self.reviewable_questions:
            return
        qid = self.reviewable_questions[self.current_q].id
        rlist = self._responses_for_question(qid)
        if not rlist:
            return
        self.current_r = (self.current_r - 1) % len(rlist)
        self._render_detail()

    def action_next_question(self) -> None:
        """Go to the next question."""
        if not self.reviewable_questions:
            return
        self.current_q = (self.current_q + 1) % len(self.reviewable_questions)
        self.current_r = 0
        self._render_detail()

    def action_prev_question(self) -> None:
        """Go to the previous question."""
        if not self.reviewable_questions:
            return
        self.current_q = (self.current_q - 1) % len(self.reviewable_questions)
        self.current_r = 0
        self._render_detail()

    def action_toggle_pending(self) -> None:
        """Toggle pending-only filtering."""
        self.pending_only = not self.pending_only
        self.current_r = 0
        state = "pending only" if self.pending_only else "all"
        self.notify(f"Showing {state} responses")
        self._render_detail()

    def action_focus_score(self) -> None:
        """Focus the score input."""
        if self.score_input is not None:
            self.set_focus(self.score_input)

    def action_save(self) -> None:  # noqa: PLR0911
        """Persist the current manual score and comment."""
        if not self.reviewable_questions:
            return
        question = self.reviewable_questions[self.current_q]
        rlist = self._responses_for_question(question.id)
        if not rlist:
            self.notify("No response to save", severity="error")
            return
        resp = rlist[self.current_r]
        response_id = resp["id"]
        manual: int | None = None
        if self.score_input is not None:
            text = self.score_input.value.strip()
            if not text:
                self.notify("Enter a score 0..points", severity="error")
                return
            try:
                manual = int(text)
            except ValueError:
                self.notify("Score must be an integer", severity="error")
                return
            points = getattr(question, "points", 0)
            if not 0 <= manual <= points:
                self.notify(f"Score must be 0..{points}", severity="error")
                return
        comment = None
        if self.comment_input is not None:
            try:
                comment = self.comment_input.text
                if comment is not None and not comment.strip():
                    comment = None
            except Exception:
                comment = None
        if manual is None:
            self.notify("No score to save", severity="error")
            return
        if self.conn is None:
            self.notify("DB not open", severity="error")
            return
        try:
            set_post_grade(
                self.conn,
                self.form,
                response_id,
                question.id,
                manual,
                comment=comment,
                reviewer=self.reviewer,
            )
            self.responses = get_responses(self.conn, form_name=self.form.name)
            self.notify(f"Saved {question.id}={manual} for #{response_id}")
            self._render_detail()
        except Exception as error:
            self.notify(f"Save failed: {error}", severity="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle save and quit buttons."""
        if event.button.id == "review-save":
            self.action_save()
        elif event.button.id == "review-quit":
            self.app.exit()
