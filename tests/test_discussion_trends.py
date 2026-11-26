"""White-box tests for discussion_trend_analysis.py (Feature 3)."""
import io
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest.mock import patch

try:
    from tests.helpers import CleanEnvTestCase, comment_event, model_issue
except ImportError:  # pragma: no cover
    from helpers import CleanEnvTestCase, comment_event, model_issue

import discussion_trend_analysis as f3
from discussion_trend_analysis import DiscussionTrends
from model import Issue


def make_issue(**kwargs):
    return Issue(model_issue(**kwargs))


class ParseDateTests(unittest.TestCase):
    def test_none_gives_none(self):
        self.assertIsNone(DiscussionTrends._parse_date(None))

    def test_date_only_becomes_utc_midnight(self):
        parsed = DiscussionTrends._parse_date('2024-01-15')
        self.assertEqual(parsed, datetime(2024, 1, 15, tzinfo=timezone.utc))

    def test_aware_timestamp_kept(self):
        parsed = DiscussionTrends._parse_date('2024-01-15T06:00:00+00:00')
        self.assertEqual(parsed.hour, 6)
        self.assertIsNotNone(parsed.tzinfo)

    def test_invalid_date_raises(self):
        with self.assertRaises(ValueError):
            DiscussionTrends._parse_date('not-a-date')

    def test_as_utc(self):
        naive = datetime(2024, 1, 1)
        self.assertEqual(DiscussionTrends._as_utc(naive).tzinfo, timezone.utc)
        aware = datetime(2024, 1, 1, tzinfo=timezone.utc)
        self.assertIs(DiscussionTrends._as_utc(aware), aware)


class MonthlyCountsTests(CleanEnvTestCase):
    def setUp(self):
        super().setUp()
        self.trends = DiscussionTrends()
        self.issues = [
            make_issue(number=1, created='2024-01-05T00:00:00Z', closed=None,
                       events=[comment_event('bob', '2024-01-06T00:00:00Z'),
                               comment_event('carol', '2024-03-01T00:00:00Z')]),
            make_issue(number=2, created='2024-01-20T00:00:00Z', closed=None,
                       events=[comment_event('bob', '2024-01-21T00:00:00Z')]),
            make_issue(number=3, created='2024-04-02T00:00:00Z', closed=None,
                       events=[]),
            # No creation date: skipped entirely, including its comment.
            make_issue(number=4, created=None, closed=None,
                       events=[comment_event('bob', '2024-01-06T00:00:00Z')]),
            # Non-comment events and dateless comments are not counted.
            make_issue(number=5, created='2024-01-25T00:00:00Z', closed=None,
                       events=[{'event_type': 'labeled', 'author': 'bob',
                                'event_date': '2024-01-26T00:00:00Z',
                                'label': 'x', 'comment': None},
                               {'event_type': 'commented', 'author': 'bob',
                                'event_date': 'not-a-date', 'label': None,
                                'comment': 'undated'}]),
        ]

    def test_monthly_counts_and_gap_filling(self):
        df = self.trends.compute_monthly_counts(self.issues)
        self.assertEqual(len(df), 4)  # Jan..Apr 2024, Feb filled with zeros
        jan = df.loc[df.index[0]]
        self.assertEqual(int(jan['issues']), 3)
        self.assertEqual(int(jan['comments']), 2)
        feb = df.iloc[1]
        self.assertEqual(int(feb['issues']), 0)
        self.assertEqual(int(feb['comments']), 0)
        mar = df.iloc[2]
        self.assertEqual(int(mar['comments']), 1)  # comment on January issue
        apr = df.iloc[3]
        self.assertEqual(int(apr['issues']), 1)

    def test_empty_input_gives_empty_frame(self):
        df = self.trends.compute_monthly_counts([])
        self.assertTrue(df.empty)

    def test_all_dateless_input_gives_empty_frame(self):
        df = self.trends.compute_monthly_counts(
            [make_issue(number=9, created=None, closed=None, events=[])])
        self.assertTrue(df.empty)

    def test_summary_text(self):
        df = self.trends.compute_monthly_counts(self.issues)
        text = DiscussionTrends._summary(df)
        self.assertIn('4 issues, 3 comments over 4 months', text)
        self.assertIn('Average comments per issue: 0.8', text)

    def test_date_filter_keeps_comments_posted_after_end_date(self):
        # Documented behaviour: the filter applies to issue creation dates,
        # so comments on an in-range issue count even after the end date.
        os.environ['start_date'] = '2024-01-01'
        os.environ['end_date'] = '2024-01-31'
        trends = DiscussionTrends()
        df = trends.compute_monthly_counts(self.issues)
        self.assertEqual(int(df['issues'].sum()), 3)
        self.assertEqual(int(df['comments'].sum()), 3)

    def test_date_filter_excludes_out_of_range_issues(self):
        os.environ['start_date'] = '2024-02-01'
        os.environ['end_date'] = '2024-12-31'
        trends = DiscussionTrends()
        df = trends.compute_monthly_counts(self.issues)
        self.assertEqual(int(df['issues'].sum()), 1)  # only the April issue
        self.assertEqual(int(df['comments'].sum()), 0)

    def test_start_date_only(self):
        os.environ['start_date'] = '2024-04-01'
        trends = DiscussionTrends()
        self.assertIsNotNone(trends.start_date)
        self.assertIsNone(trends.end_date)
        df = trends.compute_monthly_counts(self.issues)
        self.assertEqual(int(df['issues'].sum()), 1)


class RunIntegrationTests(CleanEnvTestCase):
    def _write_dataset(self):
        rows = [
            model_issue(number=1, created='2024-01-05T00:00:00Z', closed=None,
                        events=[comment_event('bob', '2024-01-06T00:00:00Z')]),
            model_issue(number=2, created='2024-02-05T00:00:00Z', closed=None,
                        events=[]),
        ]
        return self.write_json(rows)

    def test_run_writes_csv_and_png_and_prints_summary(self):
        self.point_loader_at(self._write_dataset())
        os.chdir(self.tmp)
        with patch.object(f3.plt, 'show'), \
                redirect_stdout(io.StringIO()) as out:
            DiscussionTrends().run()
        text = out.getvalue()
        self.assertIn('Discussion trends: 2 issues, 1 comments over 2 months',
                      text)
        csv_path = self.tmp / 'discussion_trends.csv'
        png_path = self.tmp / 'discussion_trends.png'
        self.assertTrue(csv_path.exists())
        self.assertTrue(png_path.exists())
        self.assertTrue(png_path.read_bytes().startswith(b'\x89PNG'))
        self.assertIn('month,issues,comments', csv_path.read_text())

    def test_run_with_no_data_in_range_prints_message_and_writes_nothing(self):
        self.point_loader_at(self._write_dataset())
        os.chdir(self.tmp)
        os.environ['start_date'] = '2022-01-01'
        os.environ['end_date'] = '2022-12-31'
        with redirect_stdout(io.StringIO()) as out:
            DiscussionTrends().run()
        self.assertIn('No issues found for the given date range.',
                      out.getvalue())
        self.assertFalse((self.tmp / 'discussion_trends.csv').exists())
        self.assertFalse((self.tmp / 'discussion_trends.png').exists())

    def test_run_with_empty_dataset(self):
        self.point_loader_at(self.write_json([], name='empty.json'))
        os.chdir(self.tmp)
        with redirect_stdout(io.StringIO()) as out:
            DiscussionTrends().run()
        self.assertIn('No issues found for the given date range.',
                      out.getvalue())


class DiscussionTrendsDefectTests(CleanEnvTestCase):
    """Defect-exposing test (Team 8 defect report DEFECT-5): Feature 3
    silently overwrites previous outputs, unlike Feature 2's versioned
    exports.  This test FAILS against the current code."""

    def test_second_run_does_not_silently_overwrite_first_outputs(self):
        first = self.write_json(
            [model_issue(number=1, created='2024-01-05T00:00:00Z',
                         closed=None, events=[])], name='first.json')
        second = self.write_json(
            [model_issue(number=1, created='2024-01-05T00:00:00Z',
                         closed=None, events=[]),
             model_issue(number=2, created='2024-03-05T00:00:00Z',
                         closed=None, events=[])], name='second.json')
        os.chdir(self.tmp)
        with patch.object(f3.plt, 'show'), redirect_stdout(io.StringIO()):
            self.point_loader_at(first)
            DiscussionTrends().run()
            first_csv = (self.tmp / 'discussion_trends.csv').read_bytes()
            self.point_loader_at(second)
            DiscussionTrends().run()
        preserved = [
            p for p in self.tmp.glob('discussion_trends*.csv')
            if p.read_bytes() == first_csv
        ]
        self.assertTrue(
            preserved,
            'The first run\'s discussion_trends.csv was silently overwritten '
            'by the second run; no versioned copy was preserved')


if __name__ == '__main__':
    unittest.main()
