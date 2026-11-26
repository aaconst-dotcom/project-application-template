"""Shared fixtures and environment hygiene for Team 8's Milestone 3 tests.

The application keeps global state: ``config._config`` is a singleton and
``data_loader._ISSUES`` caches loaded issues, and ``run.py`` copies CLI
arguments into environment variables.  ``CleanEnvTestCase`` snapshots and
restores all of that so tests are deterministic in any execution order.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import config  # noqa: E402
import data_loader  # noqa: E402

#: Environment variables the application reads through ``config``.
MANAGED_ENV_KEYS = (
    'ENPM611_PROJECT_DATA_PATH', 'label', 'user', 'start_date', 'end_date',
    'observed_at', 'include_bots', 'bot_accounts', 'stale_days',
    'response_target_hours', 'quiet_days', 'output_dir', 'feature',
    'data', 'csv_path', 'png_path',
)


class CleanEnvTestCase(unittest.TestCase):
    """TestCase that isolates config singletons, env vars and cwd."""

    def setUp(self):
        self._saved_environ = dict(os.environ)
        for key in MANAGED_ENV_KEYS:
            os.environ.pop(key, None)
        self._saved_cwd = os.getcwd()
        self._reset_singletons()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        os.chdir(self._saved_cwd)
        os.environ.clear()
        os.environ.update(self._saved_environ)
        self._reset_singletons()
        self._tmp.cleanup()

    @staticmethod
    def _reset_singletons():
        config._config = None
        data_loader._ISSUES = None

    def write_json(self, data, name='data.json'):
        path = self.tmp / name
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def point_loader_at(self, path):
        """Make the template DataLoader (Features 0/1/3) read ``path``."""
        os.environ['ENPM611_PROJECT_DATA_PATH'] = str(path)
        self._reset_singletons()


def model_issue(number=1, state='closed', labels=('kind/bug',), creator='alice',
                created='2024-01-01T00:00:00Z', closed='2024-01-11T00:00:00Z',
                assignees=(), events=None, title=None, updated=None):
    """A raw issue dict in the template export format consumed by model.py."""
    if events is None:
        events = []
        if closed is not None:
            events.append({'event_type': 'closed', 'author': creator,
                           'event_date': closed, 'label': None, 'comment': None})
    return {
        'url': f'https://github.com/example/repo/issues/{number}',
        'creator': creator,
        'labels': list(labels),
        'state': state,
        'assignees': list(assignees),
        'title': title if title is not None else f'Issue {number}',
        'text': 'body text',
        'number': number,
        'created_date': created,
        'updated_date': updated if updated is not None else (closed or created),
        'timeline_url': 'https://example.com/timeline',
        'events': events,
    }


def comment_event(author, date, **extra):
    event = {'event_type': 'commented', 'author': author,
             'event_date': date, 'label': None, 'comment': 'a comment'}
    event.update(extra)
    return event


def normalized_record(number=1, state='open', creator='alice',
                      created='2024-01-01T00:00:00Z', closed=None,
                      labels=('kind/bug',), assignees=(), events=(),
                      url=None, **extra):
    """A raw record in the format consumed by analytics.normalize (Feature 2)."""
    record = {
        'number': number,
        'url': url or f'https://github.com/example/repo/issues/{number}',
        'creator': creator,
        'labels': list(labels),
        'state': state,
        'assignees': list(assignees),
        'title': f'Issue {number}',
        'text': 'body text',
        'created_date': created,
        'updated_date': created,
        'events': list(events),
    }
    if closed is not None:
        record['closed_date'] = closed
    record.update(extra)
    return record


def normalized_event(kind, author, date, **extra):
    event = {'event_type': kind, 'author': author, 'event_date': date}
    event.update(extra)
    return event
