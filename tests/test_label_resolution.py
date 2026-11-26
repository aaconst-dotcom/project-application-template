"""White-box tests for label_resolution_analysis.py (Feature 1)."""
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

try:
    from tests.helpers import CleanEnvTestCase, comment_event, model_issue
except ImportError:  # pragma: no cover
    from helpers import CleanEnvTestCase, comment_event, model_issue

import label_resolution_analysis as f1
from label_resolution_analysis import LabelResolutionAnalysis, get_resolution_days
from model import Issue


def make_issue(**kwargs):
    return Issue(model_issue(**kwargs))


class GetResolutionDaysTests(unittest.TestCase):
    def test_closed_issue_resolution_days(self):
        issue = make_issue(created='2024-01-01T00:00:00Z',
                           closed='2024-01-11T00:00:00Z')
        self.assertEqual(get_resolution_days(issue), 10.0)

    def test_final_closed_event_wins_over_earlier_one(self):
        events = [
            {'event_type': 'closed', 'author': 'a',
             'event_date': '2024-01-05T00:00:00Z', 'label': None,
             'comment': None},
            {'event_type': 'reopened', 'author': 'a',
             'event_date': '2024-01-06T00:00:00Z', 'label': None,
             'comment': None},
            {'event_type': 'closed', 'author': 'a',
             'event_date': '2024-01-21T00:00:00Z', 'label': None,
             'comment': None},
        ]
        issue = make_issue(created='2024-01-01T00:00:00Z', closed=None,
                           events=events)
        self.assertEqual(get_resolution_days(issue), 20.0)

    def test_open_issue_has_no_resolution(self):
        issue = make_issue(state='open', closed=None, events=[])
        self.assertIsNone(get_resolution_days(issue))

    def test_closed_without_closed_event_has_no_resolution(self):
        issue = make_issue(closed=None, events=[])
        self.assertIsNone(get_resolution_days(issue))

    def test_closed_without_created_date_has_no_resolution(self):
        issue = make_issue(created=None)
        self.assertIsNone(get_resolution_days(issue))

    def test_closed_event_without_date_is_ignored(self):
        events = [{'event_type': 'closed', 'author': 'a',
                   'event_date': 'not-a-date', 'label': None, 'comment': None}]
        issue = make_issue(closed=None, events=events)
        self.assertIsNone(get_resolution_days(issue))

    def test_fractional_days(self):
        issue = make_issue(created='2024-01-01T00:00:00Z',
                           closed='2024-01-02T12:00:00Z')
        self.assertEqual(get_resolution_days(issue), 1.5)


class ComputeLabelStatsTests(CleanEnvTestCase):
    def setUp(self):
        super().setUp()
        self.analysis = LabelResolutionAnalysis(min_issues=2, top_n=15)
        self.issues = [
            make_issue(number=1, labels=('kind/bug',),
                       created='2024-01-01T00:00:00Z',
                       closed='2024-01-11T00:00:00Z'),          # 10 days
            make_issue(number=2, labels=('kind/bug',),
                       created='2024-01-01T00:00:00Z',
                       closed='2024-01-21T00:00:00Z'),          # 20 days
            make_issue(number=3, labels=('kind/bug',), state='open',
                       closed=None, events=[]),
            make_issue(number=4, labels=('kind/enhancement', 'kind/bug'),
                       created='2024-01-01T00:00:00Z',
                       closed='2024-04-10T00:00:00Z'),          # 100 days
            make_issue(number=5, labels=('area/docs',), closed=None,
                       events=[]),  # closed but no closing date recorded
        ]
        self.stats = self.analysis.compute_label_stats(self.issues)

    def test_counts_per_label_with_multi_label_issue_counted_twice(self):
        self.assertEqual(self.stats['kind/bug']['count'], 4)
        self.assertEqual(self.stats['kind/enhancement']['count'], 1)
        self.assertEqual(self.stats['area/docs']['count'], 1)

    def test_open_closed_split_and_percentage(self):
        bug = self.stats['kind/bug']
        self.assertEqual(bug['open'], 1)
        self.assertEqual(bug['closed'], 3)
        self.assertAlmostEqual(bug['open_pct'], 25.0)

    def test_median_and_mean(self):
        bug = self.stats['kind/bug']
        self.assertEqual(bug['median_days'], 20.0)   # of [10, 20, 100]
        self.assertAlmostEqual(bug['mean_days'], 130 / 3)
        self.assertEqual(bug['resolved_with_date'], 3)

    def test_label_without_dated_closures_has_none_statistics(self):
        docs = self.stats['area/docs']
        self.assertIsNone(docs['median_days'])
        self.assertIsNone(docs['mean_days'])
        self.assertEqual(docs['resolved_with_date'], 0)

    def test_empty_issue_list_gives_empty_stats(self):
        self.assertEqual(self.analysis.compute_label_stats([]), {})

    def test_ranked_labels_threshold_and_order(self):
        ranked = self.analysis.ranked_labels(self.stats)
        # kind/enhancement (1 issue) and area/docs (no median) are excluded;
        # only kind/bug meets min_issues=2 with a median.
        self.assertEqual(ranked, ['kind/bug'])

    def test_ranked_labels_sorts_slowest_first_and_truncates(self):
        issues = []
        number = 0
        for label, days in (('slow', 90), ('mid', 30), ('fast', 5)):
            for _ in range(3):
                number += 1
                issues.append(make_issue(
                    number=number, labels=(label,),
                    created='2024-01-01T00:00:00Z',
                    closed=f'2024-01-{1 + days:02d}T00:00:00Z'
                    if days < 31 else '2024-03-31T00:00:00Z'))
        analysis = LabelResolutionAnalysis(min_issues=3, top_n=2)
        stats = analysis.compute_label_stats(issues)
        self.assertEqual(analysis.ranked_labels(stats), ['slow', 'mid'])


class PrintAndPlotTests(CleanEnvTestCase):
    def setUp(self):
        super().setUp()
        self.analysis = LabelResolutionAnalysis(min_issues=1, top_n=15)
        issues = [
            make_issue(number=1, labels=('kind/bug',),
                       created='2024-01-01T00:00:00Z',
                       closed='2024-01-11T00:00:00Z'),
            make_issue(number=2, labels=('kind/bug',), state='open',
                       closed=None, events=[]),
            make_issue(number=3, labels=('area/docs',), closed=None,
                       events=[]),
        ]
        self.stats = self.analysis.compute_label_stats(issues)

    def test_print_summary_shows_table_and_finding(self):
        with redirect_stdout(io.StringIO()) as out:
            self.analysis.print_summary(self.stats)
        text = out.getvalue()
        self.assertIn('Which issue labels take the longest to resolve?', text)
        self.assertIn('kind/bug', text)
        self.assertIn('Finding:', text)
        self.assertIn('10.0 days', text)

    def test_print_summary_empty_stats(self):
        with redirect_stdout(io.StringIO()) as out:
            self.analysis.print_summary({})
        self.assertIn('at least 1 issues are shown', out.getvalue())

    def test_print_label_detail_known_label(self):
        with redirect_stdout(io.StringIO()) as out:
            self.analysis.print_label_detail('kind/bug', self.stats)
        text = out.getvalue()
        self.assertIn('Label: kind/bug', text)
        self.assertIn('Issues: 2 (open 1, closed 1, 50.0% open)', text)
        self.assertIn('Median resolution: 10.0 days', text)
        self.assertIn('based on 1 closed issues', text)

    def test_print_label_detail_label_without_dates(self):
        with redirect_stdout(io.StringIO()) as out:
            self.analysis.print_label_detail('area/docs', self.stats)
        self.assertIn('No closed issues with a recorded closing date.',
                      out.getvalue())

    def test_print_label_detail_unknown_label_lists_common_labels(self):
        with redirect_stdout(io.StringIO()) as out:
            self.analysis.print_label_detail('does/not-exist', self.stats)
        text = out.getvalue()
        self.assertIn('was not found in the dataset', text)
        self.assertIn('kind/bug', text)

    def test_plot_with_data_calls_show(self):
        with patch.object(f1.plt, 'show') as show:
            self.analysis.plot(self.stats)
        show.assert_called_once()

    def test_plot_without_eligible_labels_prints_message(self):
        with redirect_stdout(io.StringIO()) as out:
            self.analysis.plot({})
        self.assertIn('Not enough data to plot.', out.getvalue())


class RunIntegrationTests(CleanEnvTestCase):
    def _write_dataset(self):
        rows = []
        for i in range(25):
            rows.append(model_issue(
                number=100 + i, labels=('kind/bug',),
                created='2024-01-01T00:00:00Z',
                closed='2024-01-11T00:00:00Z',
                events=[comment_event('bob', '2024-01-03T00:00:00Z'),
                        {'event_type': 'closed', 'author': 'alice',
                         'event_date': '2024-01-11T00:00:00Z',
                         'label': None, 'comment': None}]))
        for i in range(22):
            rows.append(model_issue(
                number=200 + i, labels=('kind/enhancement',),
                created='2024-01-01T00:00:00Z',
                closed='2024-04-10T00:00:00Z'))
        return self.write_json(rows)

    def test_run_summary_end_to_end(self):
        self.point_loader_at(self._write_dataset())
        with patch.object(f1.plt, 'show'), \
                redirect_stdout(io.StringIO()) as out:
            LabelResolutionAnalysis().run()
        text = out.getvalue()
        self.assertIn('Loaded 47 issues', text)
        self.assertIn('kind/enhancement', text)
        self.assertIn('100.0', text)

    def test_run_with_label_from_config(self):
        self.point_loader_at(self._write_dataset())
        os.environ['label'] = 'kind/bug'
        with redirect_stdout(io.StringIO()) as out:
            LabelResolutionAnalysis().run()
        text = out.getvalue()
        self.assertIn('Label: kind/bug', text)
        self.assertIn('Median resolution: 10.0 days', text)

    def test_run_with_unknown_label_from_config(self):
        self.point_loader_at(self._write_dataset())
        os.environ['label'] = 'nope'
        with redirect_stdout(io.StringIO()) as out:
            LabelResolutionAnalysis().run()
        self.assertIn('was not found in the dataset', out.getvalue())

    def test_default_thresholds(self):
        analysis = LabelResolutionAnalysis()
        self.assertEqual(analysis.min_issues, 20)
        self.assertEqual(analysis.top_n, 15)
        self.assertIsNone(analysis.LABEL)


if __name__ == '__main__':
    unittest.main()
