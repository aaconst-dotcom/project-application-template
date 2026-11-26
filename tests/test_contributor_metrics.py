"""White-box tests for contributor_metrics.py (Feature 2 core)."""
import unittest

try:
    from tests.helpers import normalized_event as ev, normalized_record
except ImportError:  # pragma: no cover
    from helpers import normalized_event as ev, normalized_record

from analytics import normalize
from contributor_metrics import _analyze_base, _distribution, _user, analyze_contributors


def rich_issues():
    records = [
        normalized_record(
            number=1, state='open', creator='Alice',
            created='2024-01-01T00:00:00Z',
            labels=('kind/bug', 'area/core'), assignees=('Bob',),
            events=[ev('commented', 'bob', '2024-01-01T06:00:00Z'),
                    ev('commented', 'carol', '2024-01-02T00:00:00Z'),
                    ev('assigned', 'alice', '2024-01-01T02:00:00Z',
                       assignee='bob'),
                    ev('labeled', 'carol', '2024-01-01T03:00:00Z')]),
        normalized_record(
            number=2, state='closed', creator='bob',
            created='2024-01-01T00:00:00Z', closed='2024-01-21T00:00:00Z',
            labels=('kind/enhancement', 'area/docs'),
            events=[ev('commented', 'alice', '2024-01-03T00:00:00Z'),
                    ev('closed', 'bob', '2024-01-21T00:00:00Z')]),
        normalized_record(
            number=3, state='open', creator='carol',
            created='2023-06-01T00:00:00Z', labels=('kind/bug',), events=[]),
        normalized_record(
            number=4, state='open', creator='dave',
            created='2024-04-01T00:00:00Z', labels=(),
            assignees=('helper[bot]',),
            events=[ev('commented', 'dependabot[bot]', '2024-04-02T00:00:00Z'),
                    ev('commented', 'github-actions[bot]',
                       '2024-04-02T01:00:00Z')]),
        normalized_record(
            number=5, state='closed', creator='Eve',
            created='2024-03-01T00:00:00Z', closed='2024-03-11T00:00:00Z',
            labels=('area/core',),
            events=[ev('commented', 'alice', '2024-03-02T00:00:00Z', id=1),
                    ev('commented', 'alice', '2024-03-02T00:00:00Z', id=1),
                    ev('commented', 'alice', '2024-03-03T00:00:00Z'),
                    ev('commented', 'alice', '2023-12-31T00:00:00Z'),
                    ev('commented', 'alice', None),
                    ev('commented', None, '2024-03-04T00:00:00Z'),
                    ev('subscribed', 'alice', '2024-03-04T00:00:00Z'),
                    ev('reopened', 'eve', '2024-03-05T00:00:00Z')]),
    ]
    issues, errors = normalize(records)
    assert not errors, errors
    return issues


class UserHelperTests(unittest.TestCase):
    def test_user_normalizes_case_and_whitespace(self):
        self.assertEqual(_user('  Alice '), 'alice')

    def test_user_rejects_blank_unknown_and_non_strings(self):
        self.assertIsNone(_user(''))
        self.assertIsNone(_user('   '))
        self.assertIsNone(_user('unknown'))
        self.assertIsNone(_user('UNKNOWN'))
        self.assertIsNone(_user(None))
        self.assertIsNone(_user(42))


class DistributionTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_distribution([]),
                         {'samples': 0, 'median_hours': None,
                          'p90_hours': None})

    def test_single_value(self):
        self.assertEqual(_distribution([5.0]),
                         {'samples': 1, 'median_hours': 5.0, 'p90_hours': 5.0})

    def test_median_and_p90(self):
        result = _distribution([float(x) for x in range(1, 11)])
        self.assertEqual(result['samples'], 10)
        self.assertEqual(result['median_hours'], 5.5)
        self.assertEqual(result['p90_hours'], 9.0)


class AnalyzeBaseTests(unittest.TestCase):
    def setUp(self):
        self.issues = rich_issues()
        self.report = _analyze_base(self.issues)

    def test_team_totals(self):
        team = self.report['team']
        self.assertEqual(team['issues_analyzed'], 5)
        self.assertEqual(team['contributors'], 5)
        self.assertEqual(team['response_cohort'], 5)
        self.assertEqual(team['without_recorded_external_response'], 2)
        self.assertEqual(team['open_without_current_owner'], 1)

    def test_response_distribution(self):
        dist = self.report['team']['recorded_external_response']
        self.assertEqual(dist['samples'], 3)
        self.assertEqual(dist['median_hours'], 24.0)
        self.assertEqual(dist['p90_hours'], 48.0)

    def test_contributor_rows_are_case_insensitive_and_sorted(self):
        logins = [c['login'] for c in self.report['contributors']]
        self.assertEqual(logins, ['alice', 'bob', 'carol', 'dave', 'eve'])

    def test_alice_activity_counts(self):
        alice = self.report['contributors'][0]
        activity = alice['activity']
        self.assertEqual(activity['issues_reported'], 1)
        self.assertEqual(activity['issues_commented_on'], 2)
        self.assertEqual(activity['comments'], 3)
        self.assertEqual(activity['issues_triaged'], 1)
        self.assertEqual(alice['first_external_responses']['issues'], 2)
        self.assertEqual(alice['first_external_responses']['median_hours'],
                         36.0)

    def test_bob_ownership_and_old_open(self):
        bob = self.report['contributors'][1]
        self.assertEqual(bob['snapshot_ownership']['open_issues'], 1)
        self.assertEqual(bob['snapshot_ownership']['old_open_issues'], 1)

    def test_bots_are_excluded_by_default(self):
        logins = [c['login'] for c in self.report['contributors']]
        self.assertNotIn('dependabot[bot]', logins)
        self.assertNotIn('github-actions[bot]', logins)
        self.assertNotIn('helper[bot]', logins)
        quality = self.report['data_quality']
        self.assertEqual(quality['bot_participation_events_excluded'], 2)

    def test_bots_are_included_when_requested(self):
        report = _analyze_base(self.issues, include_bots=True)
        logins = [c['login'] for c in report['contributors']]
        self.assertIn('dependabot[bot]', logins)
        self.assertIn('helper[bot]', logins)

    def test_custom_bot_accounts_are_excluded(self):
        report = _analyze_base(self.issues, bot_accounts=('Carol',))
        logins = [c['login'] for c in report['contributors']]
        self.assertNotIn('carol', logins)

    def test_data_quality_counters(self):
        quality = self.report['data_quality']
        self.assertEqual(quality['events_before_creation_excluded'], 1)
        self.assertEqual(quality['participation_events_missing_date'], 1)
        self.assertEqual(quality['participation_events_missing_actor'], 1)
        self.assertEqual(quality['nonparticipation_events_excluded'], 1)
        self.assertEqual(quality['issues_without_confirmed_timeline'], 5)

    def test_monthly_buckets(self):
        monthly = self.report['monthly']
        self.assertEqual(monthly['2024-01']['active_contributors'], 3)
        self.assertEqual(monthly['2024-01']['comments'], 3)
        self.assertEqual(monthly['2023-06']['issues_reported'], 1)

    def test_evidence_lists(self):
        evidence = self.report['evidence']
        self.assertEqual(evidence['open_without_current_owner'],
                         ['https://github.com/example/repo/issues/3'])
        self.assertEqual(len(evidence['without_recorded_external_response']),
                         2)

    def test_scope_reference_is_latest_activity(self):
        self.assertEqual(self.report['scope']['snapshot_reference'],
                         '2024-04-02T01:00:00+00:00')
        self.assertEqual(self.report['scope']['reference_basis'],
                         'latest_recorded_activity')

    def test_empty_dataset(self):
        report = _analyze_base([])
        self.assertEqual(report['team']['issues_analyzed'], 0)
        self.assertEqual(report['contributors'], [])
        self.assertIsNone(report['scope']['snapshot_reference'])
        self.assertEqual(report['scope']['reference_basis'], 'unavailable')

    def test_duplicate_issue_ids_are_skipped(self):
        doubled = self.issues + [dict(self.issues[0])]
        report = _analyze_base(doubled)
        self.assertEqual(report['team']['issues_analyzed'], 5)
        self.assertEqual(report['data_quality']['duplicate_issues_skipped'], 1)

    def test_missing_creation_date_is_counted(self):
        raw = normalized_record(number=9, created=None)
        raw['created_date'] = None
        issues, _ = normalize([raw])
        issues[0]['created'] = None
        report = _analyze_base(issues)
        self.assertEqual(report['data_quality']['issues_missing_creation_date'],
                         1)

    def test_window_restricts_activity_but_not_ownership(self):
        report = _analyze_base(self.issues, since='2024-03-01T00:00:00Z',
                               until='2024-03-31T23:59:59Z')
        bob = next(c for c in report['contributors'] if c['login'] == 'bob')
        # Ownership is snapshot-wide even though Bob had no March activity.
        self.assertEqual(bob['snapshot_ownership']['open_issues'], 1)
        self.assertEqual(bob['activity']['comments'], 0)


class AnalyzeValidationTests(unittest.TestCase):
    def setUp(self):
        self.issues = rich_issues()

    def test_stale_days_must_be_nonnegative_int(self):
        for bad in (-1, 1.5, True, '90'):
            with self.assertRaises(ValueError, msg=f'stale_days={bad!r}'):
                _analyze_base(self.issues, stale_days=bad)

    def test_bad_since_raises(self):
        with self.assertRaises(ValueError):
            _analyze_base(self.issues, since='not-a-date')

    def test_bad_until_raises(self):
        with self.assertRaises(ValueError):
            _analyze_base(self.issues, until='2024-13-01')

    def test_bad_observed_at_raises(self):
        with self.assertRaises(ValueError):
            _analyze_base(self.issues, observed_at='junk')

    def test_since_after_until_raises(self):
        with self.assertRaises(ValueError):
            _analyze_base(self.issues, since='2024-05-01T00:00:00Z',
                          until='2024-04-01T00:00:00Z')

    def test_observed_at_before_latest_activity_raises(self):
        with self.assertRaises(ValueError):
            _analyze_base(self.issues, observed_at='2024-01-01T00:00:00Z')

    def test_until_after_snapshot_reference_raises(self):
        with self.assertRaises(ValueError):
            _analyze_base(self.issues, observed_at='2024-04-02T01:00:00Z',
                          until='2024-05-01T00:00:00Z')

    def test_explicit_observed_at_is_used(self):
        report = _analyze_base(self.issues, observed_at='2024-04-02T01:00:00Z')
        self.assertEqual(report['scope']['reference_basis'], 'provided')
        self.assertEqual(report['scope']['snapshot_reference'],
                         '2024-04-02T01:00:00+00:00')


class AnalyzeContributorsEntryPointTests(unittest.TestCase):
    def test_full_report_has_health_section(self):
        report = analyze_contributors(rich_issues())
        self.assertIn('health', report['team'])
        for contributor in report['contributors']:
            self.assertIn('health', contributor)

    def test_options_are_passed_through(self):
        report = analyze_contributors(rich_issues(), include_bots=True,
                                      stale_days=10)
        self.assertTrue(report['scope']['include_bots'])
        self.assertEqual(report['scope']['stale_days'], 10)


if __name__ == '__main__':
    unittest.main()
