"""White-box tests for run.py dispatch and example_analysis.py (Feature 0)."""
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

try:
    from tests.helpers import (CleanEnvTestCase, comment_event, model_issue,
                               normalized_record)
except ImportError:  # pragma: no cover
    from helpers import (CleanEnvTestCase, comment_event, model_issue,
                         normalized_record)

import example_analysis
import run as run_module
from example_analysis import ExampleAnalysis


class ParseArgsTests(CleanEnvTestCase):
    def test_minimal_args_defaults(self):
        args = run_module.parse_args(['--feature', '1'])
        self.assertEqual(args.feature, 1)
        self.assertIsNone(args.user)
        self.assertIsNone(args.label)
        self.assertIsNone(args.data)
        self.assertIsNone(args.start_date)
        self.assertIsNone(args.end_date)
        self.assertIsNone(args.include_bots)
        self.assertEqual(args.csv_path, 'contributor_activity.csv')
        self.assertEqual(args.png_path, 'contributor_activity.png')

    def test_short_flag_and_all_options(self):
        args = run_module.parse_args([
            '-f', '2', '-u', 'alice', '-l', 'kind/bug', '--data', 'x.json',
            '--since', '2024-01-01', '--until', '2024-02-01',
            '--observed-at', '2024-03-01', '--include-bots',
            '--bot', 'bot1', '--bot', 'bot2', '--stale-days', '7',
            '--response-target-hours', '12.5', '--quiet-days', '3',
            '--output-dir', 'out', '--csv', 'a.csv', '--png', 'b.png'])
        self.assertEqual(args.feature, 2)
        self.assertEqual(args.user, 'alice')
        self.assertEqual(args.label, 'kind/bug')
        self.assertEqual(args.start_date, '2024-01-01')
        self.assertEqual(args.end_date, '2024-02-01')
        self.assertEqual(args.observed_at, '2024-03-01')
        self.assertTrue(args.include_bots)
        self.assertEqual(args.bot_accounts, ['bot1', 'bot2'])
        self.assertEqual(args.stale_days, 7)
        self.assertEqual(args.response_target_hours, 12.5)
        self.assertEqual(args.quiet_days, 3)
        self.assertEqual(args.output_dir, 'out')
        self.assertEqual(args.csv_path, 'a.csv')
        self.assertEqual(args.png_path, 'b.png')

    def test_no_csv_and_no_png(self):
        args = run_module.parse_args(['--feature', '2', '--no-csv',
                                      '--no-png'])
        self.assertIsNone(args.csv_path)
        self.assertIsNone(args.png_path)

    def test_csv_and_no_csv_are_mutually_exclusive(self):
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                run_module.parse_args(['--feature', '2', '--csv', 'a.csv',
                                       '--no-csv'])
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_feature_is_rejected(self):
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                run_module.parse_args([])
        self.assertEqual(ctx.exception.code, 2)

    def test_invalid_feature_choice_is_rejected(self):
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                run_module.parse_args(['--feature', '9'])
        self.assertEqual(ctx.exception.code, 2)

    def test_non_integer_feature_is_rejected(self):
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                run_module.parse_args(['--feature', 'abc'])
        self.assertEqual(ctx.exception.code, 2)


def feature_dataset(tmp_write):
    """Three model-format issues shared by the dispatch tests."""
    return tmp_write([
        model_issue(number=1, labels=('kind/bug',),
                    created='2024-01-01T00:00:00Z',
                    closed='2024-01-11T00:00:00Z',
                    events=[comment_event('bob', '2024-01-03T00:00:00Z'),
                            {'event_type': 'closed', 'author': 'alice',
                             'event_date': '2024-01-11T00:00:00Z',
                             'label': None, 'comment': None}]),
        model_issue(number=2, labels=('kind/bug',), state='open',
                    created='2024-02-01T00:00:00Z', closed=None,
                    events=[comment_event('alice', '2024-02-02T00:00:00Z')]),
        model_issue(number=3, labels=('area/docs',),
                    created='2024-02-10T00:00:00Z',
                    closed='2024-02-20T00:00:00Z'),
    ])


class MainDispatchTests(CleanEnvTestCase):
    def test_feature_1_dispatch(self):
        self.point_loader_at(feature_dataset(self.write_json))
        import label_resolution_analysis as f1
        with patch.object(f1.plt, 'show'), \
                redirect_stdout(io.StringIO()) as out:
            run_module.main(['--feature', '1'])
        self.assertIn('Loaded 3 issues', out.getvalue())
        self.assertIn('Which issue labels take the longest', out.getvalue())

    def test_feature_1_with_label_dispatch(self):
        self.point_loader_at(feature_dataset(self.write_json))
        with redirect_stdout(io.StringIO()) as out:
            run_module.main(['--feature', '1', '--label', 'kind/bug'])
        self.assertIn('Label: kind/bug', out.getvalue())

    def test_feature_3_dispatch(self):
        self.point_loader_at(feature_dataset(self.write_json))
        os.chdir(self.tmp)
        import discussion_trend_analysis as f3
        with patch.object(f3.plt, 'show'), \
                redirect_stdout(io.StringIO()) as out:
            run_module.main(['--feature', '3'])
        self.assertIn('Discussion trends: 3 issues, 2 comments', out.getvalue())
        self.assertTrue((self.tmp / 'discussion_trends.csv').exists())

    def test_feature_0_dispatch(self):
        self.point_loader_at(feature_dataset(self.write_json))
        with patch.object(example_analysis.plt, 'show'), \
                redirect_stdout(io.StringIO()) as out:
            run_module.main(['--feature', '0'])
        self.assertIn('Found 4 events across 3 issues.', out.getvalue())

    def test_feature_2_dispatch_writes_reports(self):
        data = self.write_json([normalized_record(
            number=1, state='open', creator='alice',
            created='2024-01-01T00:00:00Z', events=[])], name='f2.json')
        with redirect_stdout(io.StringIO()) as out:
            run_module.main(['--feature', '2', '--data', str(data),
                             '--output-dir', str(self.tmp)])
        self.assertIn('Analyzed 1 issues; 1 eligible contributors.',
                      out.getvalue())
        self.assertTrue((self.tmp / 'contributor_activity.csv').exists())
        self.assertTrue((self.tmp / 'contributor_activity.png').exists())

    def test_feature_2_with_label_is_a_clean_failure(self):
        data = self.write_json([], name='f2.json')
        with self.assertRaises(SystemExit) as ctx:
            run_module.main(['--feature', '2', '--data', str(data),
                             '--label', 'kind/bug'])
        self.assertIn('--label is not currently supported',
                      str(ctx.exception))

    def test_feature_2_missing_data_file_is_a_clean_failure(self):
        with self.assertRaises(SystemExit) as ctx:
            run_module.main(['--feature', '2',
                             '--data', str(self.tmp / 'nope.json')])
        self.assertIn('Analysis failed:', str(ctx.exception))

    def test_feature_1_missing_data_file_is_a_clean_failure(self):
        self.point_loader_at(self.tmp / 'nope.json')
        with self.assertRaises(SystemExit) as ctx:
            run_module.main(['--feature', '1'])
        self.assertIn('Analysis failed:', str(ctx.exception))

    def test_run_contributor_analysis_passes_settings(self):
        data = self.write_json([normalized_record(
            number=1, state='open', creator='alice',
            created='2024-01-01T00:00:00Z', events=[])], name='f2.json')
        args = run_module.parse_args(['--feature', '2', '--data', str(data),
                                      '--output-dir', str(self.tmp),
                                      '--no-csv', '--no-png'])
        run_module.config.overwrite_from_args(args)
        report = run_module.run_contributor_analysis(args)
        self.assertEqual(report['team']['issues_analyzed'], 1)


class ExampleAnalysisTests(CleanEnvTestCase):
    def test_counts_all_events_without_user_filter(self):
        self.point_loader_at(feature_dataset(self.write_json))
        with patch.object(example_analysis.plt, 'show'), \
                redirect_stdout(io.StringIO()) as out:
            ExampleAnalysis().run()
        self.assertIn('Found 4 events across 3 issues.', out.getvalue())

    def test_counts_only_the_given_users_events(self):
        self.point_loader_at(feature_dataset(self.write_json))
        os.environ['user'] = 'bob'
        with patch.object(example_analysis.plt, 'show'), \
                redirect_stdout(io.StringIO()) as out:
            ExampleAnalysis().run()
        self.assertIn('Found 1 events across 3 issues for bob.',
                      out.getvalue())

    def test_user_with_no_events(self):
        self.point_loader_at(feature_dataset(self.write_json))
        os.environ['user'] = 'nobody'
        with patch.object(example_analysis.plt, 'show'), \
                redirect_stdout(io.StringIO()) as out:
            ExampleAnalysis().run()
        self.assertIn('Found 0 events across 3 issues for nobody.',
                      out.getvalue())


if __name__ == '__main__':
    unittest.main()
