"""White-box tests for contributor_activity_analysis.py and
contributor_activity_exports.py (Feature 2 coordination and output)."""
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path

try:
    from tests.helpers import (CleanEnvTestCase, normalized_event as ev,
                               normalized_record)
except ImportError:  # pragma: no cover
    from helpers import CleanEnvTestCase, normalized_event as ev, normalized_record

import contributor_activity_exports as exports
from contributor_activity_analysis import ContributorActivityAnalysis, main
from contributor_activity_exports import export_report, versioned_export_paths


def sample_records():
    return [
        normalized_record(
            number=1, state='open', creator='Alice',
            created='2024-01-01T00:00:00Z',
            labels=('kind/bug', 'area/core'), assignees=('Bob',),
            events=[ev('commented', 'bob', '2024-01-01T06:00:00Z'),
                    ev('assigned', 'alice', '2024-01-01T02:00:00Z',
                       assignee='bob')]),
        normalized_record(
            number=2, state='closed', creator='bob',
            created='2024-01-01T00:00:00Z', closed='2024-01-21T00:00:00Z',
            labels=('kind/enhancement',),
            events=[ev('commented', 'alice', '2024-01-03T00:00:00Z')]),
        normalized_record(
            number=3, state='open', creator='carol',
            created='2023-06-01T00:00:00Z', labels=('kind/bug',), events=[]),
    ]


class AnalysisLoadTests(CleanEnvTestCase):
    def test_build_report_from_data_file(self):
        path = self.write_json(sample_records())
        report = ContributorActivityAnalysis(data_path=path).build_report()
        self.assertEqual(report['import'], {'accepted': 3, 'rejected': 0,
                                            'errors': []})
        self.assertEqual(report['team']['issues_analyzed'], 3)
        self.assertEqual([c['login'] for c in report['contributors']],
                         ['alice', 'bob', 'carol'])

    def test_rejected_records_are_counted_not_fatal(self):
        records = sample_records() + [
            normalized_record(number=1),                 # duplicate
            normalized_record(number=9, state='weird'),  # invalid state
            'junk',                                      # not an object
        ]
        path = self.write_json(records)
        report = ContributorActivityAnalysis(data_path=path).build_report()
        self.assertEqual(report['import']['accepted'], 3)
        self.assertEqual(report['import']['rejected'], 3)

    def test_all_records_invalid_raises_value_error(self):
        path = self.write_json([normalized_record(number=9, state='weird')])
        with self.assertRaises(ValueError) as ctx:
            ContributorActivityAnalysis(data_path=path).build_report()
        self.assertIn('No valid issues to analyze', str(ctx.exception))

    def test_empty_dataset_builds_empty_report(self):
        path = self.write_json([])
        report = ContributorActivityAnalysis(data_path=path).build_report()
        self.assertEqual(report['team']['issues_analyzed'], 0)
        self.assertEqual(report['contributors'], [])

    def test_missing_data_file_raises_oserror(self):
        analysis = ContributorActivityAnalysis(
            data_path=self.tmp / 'nope.json')
        with self.assertRaises(OSError):
            analysis.build_report()

    def test_malformed_json_raises_value_error(self):
        path = self.tmp / 'bad.json'
        path.write_text('{oops', encoding='utf-8')
        with self.assertRaises(ValueError):
            ContributorActivityAnalysis(data_path=path).build_report()

    def test_non_array_json_raises_value_error(self):
        path = self.write_json({'a': 1})
        with self.assertRaises(ValueError) as ctx:
            ContributorActivityAnalysis(data_path=path).build_report()
        self.assertIn('Expected a JSON array', str(ctx.exception))

    def test_loads_through_template_data_loader_when_no_data_path(self):
        path = self.write_json(sample_records())
        self.point_loader_at(path)
        report = ContributorActivityAnalysis().build_report()
        self.assertEqual(report['team']['issues_analyzed'], 3)

    def test_defaults(self):
        analysis = ContributorActivityAnalysis(data_path='x.json')
        self.assertEqual(analysis.stale_days, 90)
        self.assertEqual(analysis.response_target_hours, 24)
        self.assertEqual(analysis.quiet_days, 30)
        self.assertFalse(analysis.include_bots)
        self.assertEqual(analysis.output_dir, Path('.'))

    def test_include_bots_must_be_bool(self):
        with self.assertRaises(ValueError):
            ContributorActivityAnalysis(data_path='x.json',
                                        include_bots='yes')

    def test_options_override_defaults(self):
        analysis = ContributorActivityAnalysis(
            data_path='x.json', stale_days=7, quiet_days=3,
            response_target_hours=12, user='alice',
            output_dir=str(self.tmp))
        self.assertEqual(analysis.stale_days, 7)
        self.assertEqual(analysis.quiet_days, 3)
        self.assertEqual(analysis.response_target_hours, 12)
        self.assertEqual(analysis.user, 'alice')
        self.assertEqual(analysis.output_dir, self.tmp)


class AnalysisPeriodAndFilterTests(CleanEnvTestCase):
    def test_date_only_end_date_covers_the_whole_day(self):
        path = self.write_json(sample_records())
        analysis = ContributorActivityAnalysis(
            data_path=path, start_date='2024-01-01', end_date='2024-01-01')
        since, until = analysis._period(
            analysis._load_issues()[0])
        self.assertTrue(since.startswith('2024-01-01'))
        self.assertTrue(until.startswith('2024-01-01T23:59:59'))

    def test_bad_start_date_raises(self):
        path = self.write_json(sample_records())
        analysis = ContributorActivityAnalysis(data_path=path,
                                               start_date='bogus')
        with self.assertRaises(ValueError):
            analysis.build_report()

    def test_user_filter_is_case_insensitive(self):
        path = self.write_json(sample_records())
        report = ContributorActivityAnalysis(
            data_path=path, user=' ALICE ').build_report()
        self.assertEqual([c['login'] for c in report['contributors']],
                         ['alice'])
        self.assertEqual(report['contributor_filter'], 'alice')

    def test_unknown_user_raises(self):
        path = self.write_json(sample_records())
        with self.assertRaises(ValueError) as ctx:
            ContributorActivityAnalysis(
                data_path=path, user='nosuchuser').build_report()
        self.assertIn('No eligible contributor found', str(ctx.exception))

    def test_windowed_report(self):
        path = self.write_json(sample_records())
        report = ContributorActivityAnalysis(
            data_path=path, start_date='2024-01-01', end_date='2024-01-02'
        ).build_report()
        self.assertEqual(report['scope']['since_inclusive'],
                         '2024-01-01T00:00:00+00:00')
        self.assertTrue(report['scope']['until_inclusive']
                        .startswith('2024-01-02'))


class AnalysisRunTests(CleanEnvTestCase):
    def test_run_writes_real_csv_and_png_and_prints_summary(self):
        path = self.write_json(sample_records())
        analysis = ContributorActivityAnalysis(data_path=path,
                                               output_dir=str(self.tmp))
        with redirect_stdout(io.StringIO()) as out:
            report = analysis.run()
        text = out.getvalue()
        self.assertIn('Analyzed 3 issues; 3 eligible contributors.', text)
        self.assertIn('Response observations: 2;', text)
        self.assertIn('rejected records: 0.', text)
        csv_path = self.tmp / 'contributor_activity.csv'
        png_path = self.tmp / 'contributor_activity.png'
        self.assertTrue(csv_path.exists())
        self.assertTrue(png_path.read_bytes().startswith(b'\x89PNG'))
        rows = csv_path.read_text(encoding='utf-8-sig').splitlines()
        self.assertIn('login', rows[0])
        self.assertEqual(len(rows), 4)  # header + 3 contributors
        self.assertEqual(report['team']['issues_analyzed'], 3)

    def test_run_without_exports(self):
        path = self.write_json(sample_records())
        analysis = ContributorActivityAnalysis(data_path=path,
                                               output_dir=str(self.tmp))
        with redirect_stdout(io.StringIO()):
            analysis.run(csv_path=None, png_path=None)
        self.assertEqual(list(self.tmp.iterdir()), [path])

    def test_run_without_summary_prints_nothing(self):
        path = self.write_json(sample_records())
        analysis = ContributorActivityAnalysis(data_path=path,
                                               output_dir=str(self.tmp))
        with redirect_stdout(io.StringIO()) as out:
            analysis.run(csv_path=None, png_path=None, print_summary=False)
        self.assertEqual(out.getvalue(), '')

    def test_run_into_missing_output_directory_raises(self):
        path = self.write_json(sample_records())
        analysis = ContributorActivityAnalysis(
            data_path=path, output_dir=str(self.tmp / 'missing'))
        with self.assertRaises((OSError, ValueError)):
            with redirect_stdout(io.StringIO()):
                analysis.run()


class AnalysisMainTests(CleanEnvTestCase):
    def test_main_prints_json_report_by_default(self):
        path = self.write_json(sample_records())
        with redirect_stdout(io.StringIO()) as out:
            main(['--data', str(path), '--output-dir', str(self.tmp)])
        parsed = json.loads(out.getvalue())
        self.assertEqual(parsed['team']['issues_analyzed'], 3)

    def test_main_summary_flag_prints_summary_instead(self):
        path = self.write_json(sample_records())
        with redirect_stdout(io.StringIO()) as out:
            main(['--data', str(path), '--output-dir', str(self.tmp),
                  '--summary'])
        self.assertIn('Analyzed 3 issues', out.getvalue())

    def test_main_requires_data_argument(self):
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                main([])
        self.assertEqual(ctx.exception.code, 2)

    def test_main_missing_file_exits_with_error(self):
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                main(['--data', str(self.tmp / 'nope.json')])
        self.assertEqual(ctx.exception.code, 2)


class ContributorAnalysisDefectTests(CleanEnvTestCase):
    """Defect-exposing test (Team 8 defect report DEFECT-4): with --user,
    the terminal summary still reports the pre-filter contributor total.
    This test FAILS against the current code."""

    def test_user_filtered_summary_reports_filtered_contributor_count(self):
        path = self.write_json(sample_records())
        analysis = ContributorActivityAnalysis(data_path=path, user='alice',
                                               output_dir=str(self.tmp))
        with redirect_stdout(io.StringIO()) as out:
            analysis.run(csv_path=None, png_path=None)
        self.assertIn('Analyzed 3 issues; 1 eligible contributors.',
                      out.getvalue())


class ExportBytesTests(CleanEnvTestCase):
    def _report(self):
        path = self.write_json(sample_records())
        return ContributorActivityAnalysis(data_path=path).build_report()

    def test_csv_bytes_header_rows_and_bom(self):
        data = exports._csv_bytes(self._report())
        self.assertTrue(data.startswith(b'\xef\xbb\xbf'))  # utf-8-sig BOM
        text = data.decode('utf-8-sig')
        lines = text.splitlines()
        self.assertIn('login,issues_reported', lines[0])
        self.assertEqual(len(lines), 4)
        self.assertTrue(any(line.startswith('alice,') for line in lines))

    def test_csv_bytes_escapes_formula_injection_logins(self):
        report = self._report()
        report['contributors'][0]['login'] = '=evil'
        text = exports._csv_bytes(report).decode('utf-8-sig')
        self.assertIn("'=evil", text)

    def test_csv_bytes_empty_contributors_is_header_only(self):
        path = self.write_json([])
        report = ContributorActivityAnalysis(data_path=path).build_report()
        lines = exports._csv_bytes(report).decode('utf-8-sig').splitlines()
        self.assertEqual(len(lines), 1)

    def test_png_bytes_renders_real_chart(self):
        data = exports._png_bytes(self._report())
        self.assertTrue(data.startswith(b'\x89PNG'))

    def test_png_bytes_with_empty_report(self):
        path = self.write_json([])
        report = ContributorActivityAnalysis(data_path=path).build_report()
        data = exports._png_bytes(report)
        self.assertTrue(data.startswith(b'\x89PNG'))

    def test_png_bytes_with_filtered_report(self):
        path = self.write_json(sample_records())
        report = ContributorActivityAnalysis(
            data_path=path, user='alice').build_report()
        data = exports._png_bytes(report)
        self.assertTrue(data.startswith(b'\x89PNG'))


class ExportReportTests(CleanEnvTestCase):
    def _report(self):
        path = self.write_json(sample_records())
        return ContributorActivityAnalysis(data_path=path).build_report()

    def test_export_report_writes_both_formats(self):
        written = export_report(self._report(),
                                csv_path=self.tmp / 'out.csv',
                                png_path=self.tmp / 'out.png')
        self.assertEqual(len(written), 2)
        self.assertTrue((self.tmp / 'out.csv').exists())
        self.assertTrue((self.tmp / 'out.png').read_bytes()
                        .startswith(b'\x89PNG'))

    def test_export_report_csv_only_and_none(self):
        written = export_report(self._report(),
                                csv_path=self.tmp / 'only.csv', png_path=None)
        self.assertEqual([Path(p).name for p in written], ['only.csv'])
        self.assertEqual(export_report(self._report()), [])

    def test_export_report_refuses_existing_destination(self):
        target = self.tmp / 'out.csv'
        target.write_text('keep')
        written = export_report(self._report(), csv_path=target,
                                png_path=None)
        # Versioned instead of overwritten.
        self.assertEqual([Path(p).name for p in written], ['out_2.csv'])
        self.assertEqual(target.read_text(), 'keep')

    def test_versioned_paths_edge_cases(self):
        self.assertEqual(versioned_export_paths(None, None), (None, None))
        with self.assertRaises(ValueError):
            versioned_export_paths(self.tmp / 'same', self.tmp / 'same')
        with self.assertRaises(IsADirectoryError):
            versioned_export_paths(self.tmp, None)
        with self.assertRaises(FileNotFoundError):
            versioned_export_paths(self.tmp / 'missing' / 'x.csv', None)


if __name__ == '__main__':
    unittest.main()
