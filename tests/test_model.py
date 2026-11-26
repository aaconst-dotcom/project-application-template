"""White-box tests for model.py (Issue, Event, State)."""
import unittest
from datetime import datetime, timezone

try:
    from tests.helpers import CleanEnvTestCase, model_issue
except ImportError:  # pragma: no cover
    from helpers import CleanEnvTestCase, model_issue

from model import Event, Issue, State


class StateTests(unittest.TestCase):
    def test_state_members_and_values(self):
        self.assertEqual(State.open.value, 'open')
        self.assertEqual(State.closed.value, 'closed')
        self.assertIs(State['open'], State.open)
        self.assertIs(State['closed'], State.closed)
        self.assertIsInstance(State.open, str)


class EventTests(unittest.TestCase):
    def test_event_from_full_json(self):
        event = Event({'event_type': 'commented', 'author': 'bob',
                       'event_date': '2024-01-03T04:05:06Z',
                       'label': 'kind/bug', 'comment': 'hello'})
        self.assertEqual(event.event_type, 'commented')
        self.assertEqual(event.author, 'bob')
        self.assertEqual(event.label, 'kind/bug')
        self.assertEqual(event.comment, 'hello')
        self.assertEqual(event.event_date,
                         datetime(2024, 1, 3, 4, 5, 6, tzinfo=timezone.utc))

    def test_event_none_json_leaves_defaults(self):
        event = Event(None)
        self.assertIsNone(event.event_type)
        self.assertIsNone(event.author)
        self.assertIsNone(event.event_date)
        self.assertIsNone(event.label)
        self.assertIsNone(event.comment)

    def test_event_unparseable_date_is_ignored_not_fatal(self):
        event = Event({'event_type': 'closed', 'author': 'a',
                       'event_date': 'not-a-date'})
        self.assertEqual(event.event_type, 'closed')
        self.assertIsNone(event.event_date)

    def test_event_missing_date_is_none(self):
        event = Event({'event_type': 'labeled', 'author': 'a'})
        self.assertIsNone(event.event_date)
        self.assertIsNone(event.comment)


class IssueTests(CleanEnvTestCase):
    def test_issue_defaults_without_json(self):
        issue = Issue()
        self.assertIsNone(issue.url)
        self.assertIsNone(issue.creator)
        self.assertEqual(issue.labels, [])
        self.assertIsNone(issue.state)
        self.assertEqual(issue.assignees, [])
        self.assertEqual(issue.number, -1)
        self.assertIsNone(issue.created_date)
        self.assertIsNone(issue.updated_date)
        self.assertEqual(issue.events, [])

    def test_issue_from_full_json(self):
        raw = model_issue(number=42, state='open', labels=['a', 'b'],
                          creator='carol', assignees=['dave'],
                          events=[{'event_type': 'commented', 'author': 'dave',
                                   'event_date': '2024-01-02T00:00:00Z',
                                   'label': None, 'comment': 'hi'}])
        issue = Issue(raw)
        self.assertEqual(issue.number, 42)
        self.assertIs(issue.state, State.open)
        self.assertEqual(issue.labels, ['a', 'b'])
        self.assertEqual(issue.creator, 'carol')
        self.assertEqual(issue.assignees, ['dave'])
        self.assertEqual(issue.title, 'Issue 42')
        self.assertEqual(len(issue.events), 1)
        self.assertIsInstance(issue.events[0], Event)
        self.assertEqual(issue.events[0].author, 'dave')
        self.assertEqual(issue.created_date,
                         datetime(2024, 1, 1, tzinfo=timezone.utc))

    def test_issue_number_given_as_string_is_coerced(self):
        raw = model_issue()
        raw['number'] = '7'
        self.assertEqual(Issue(raw).number, 7)

    def test_issue_unparseable_number_keeps_default(self):
        raw = model_issue()
        raw['number'] = 'not-a-number'
        self.assertEqual(Issue(raw).number, -1)

    def test_issue_missing_number_keeps_default(self):
        raw = model_issue()
        del raw['number']
        self.assertEqual(Issue(raw).number, -1)

    def test_issue_missing_optional_fields(self):
        issue = Issue({'state': 'closed'})
        self.assertEqual(issue.labels, [])
        self.assertEqual(issue.assignees, [])
        self.assertEqual(issue.events, [])
        self.assertIsNone(issue.created_date)
        self.assertIsNone(issue.url)

    def test_issue_unparseable_dates_are_ignored(self):
        raw = model_issue(created='garbage', closed=None, updated='also-bad')
        raw['events'] = []
        issue = Issue(raw)
        self.assertIsNone(issue.created_date)
        self.assertIsNone(issue.updated_date)

    def test_issue_none_dates_are_ignored(self):
        raw = model_issue(created=None, closed=None, updated=None)
        raw['events'] = []
        issue = Issue(raw)
        self.assertIsNone(issue.created_date)
        self.assertIsNone(issue.updated_date)


class IssueDefectTests(CleanEnvTestCase):
    """Defect-exposing tests: these assert the *graceful* behaviour a data
    loader should have.  They FAIL against the current code (see the Team 8
    defect report, DEFECT-1)."""

    def _assert_graceful(self, raw):
        try:
            Issue(raw)
        except ValueError:
            return  # a clean, documented error type is acceptable
        except Exception as exc:  # noqa: BLE001 - we classify it below
            self.fail(
                'Expected a clean ValueError for a malformed issue record, '
                f'but got an unhandled {type(exc).__name__}: {exc}')
        self.fail('Expected ValueError for a malformed issue record, '
                  'but the record was silently accepted')

    def test_unknown_state_value_is_rejected_gracefully(self):
        self._assert_graceful(model_issue(state='weird'))

    def test_capitalised_state_value_is_rejected_gracefully(self):
        self._assert_graceful(model_issue(state='Open'))


if __name__ == '__main__':
    unittest.main()
