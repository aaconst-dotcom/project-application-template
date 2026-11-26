"""White-box tests for contributor_health_metrics.py (Feature 2 health)."""
import unittest

try:
    from tests.helpers import normalized_event as ev, normalized_record
except ImportError:  # pragma: no cover
    from helpers import normalized_event as ev, normalized_record

from analytics import normalize
from contributor_health_metrics import (_distribution, _identity, _login,
                                        enrich_contributor_report)
from contributor_metrics import _analyze_base


def base_report(records, **options):
    issues, errors = normalize(records)
    assert not errors, errors
    return issues, _analyze_base(issues, **options)


class HelperTests(unittest.TestCase):
    def test_login_normalization(self):
        self.assertEqual(_login('  Bob '), 'bob')
        self.assertIsNone(_login('unknown'))
        self.assertIsNone(_login(''))
        self.assertIsNone(_login(None))
        self.assertIsNone(_login(3.5))

    def test_identity_from_github_and_api_urls(self):
        self.assertEqual(
            _identity({'number': 4,
                       'url': 'https://github.com/Owner/Repo/issues/4'}),
            'https://github.com/owner/repo/issues/4')
        self.assertEqual(
            _identity({'number': 4,
                       'url': 'https://api.github.com/repos/Owner/Repo/issues/4'}),
            'https://github.com/owner/repo/issues/4')

    def test_identity_fallback_for_other_urls(self):
        self.assertEqual(_identity({'number': 2, 'url': 'https://x.test/i/2'}),
                         'https://x.test/i/2#2')
        self.assertEqual(_identity({'number': 2, 'url': ''}), 'import#2')
        self.assertEqual(_identity({'number': 2}), 'import#2')

    def test_distribution_units(self):
        self.assertEqual(_distribution([], 'days'),
                         {'samples': 0, 'median_days': None, 'p90_days': None})
        self.assertEqual(_distribution([2.0, 4.0], 'hours'),
                         {'samples': 2, 'median_hours': 3.0, 'p90_hours': 4.0})


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.issues, self.report = base_report(
            [normalized_record(number=1)])

    def test_response_target_must_be_positive_finite_number(self):
        for bad in (0, -1, True, float('inf'), float('nan'), '24'):
            with self.assertRaises(ValueError, msg=f'value={bad!r}'):
                enrich_contributor_report(self.issues, self.report,
                                          response_target_hours=bad)

    def test_quiet_days_must_be_nonnegative_int(self):
        for bad in (-1, 1.5, True, '30'):
            with self.assertRaises(ValueError, msg=f'value={bad!r}'):
                enrich_contributor_report(self.issues, self.report,
                                          quiet_days=bad)

    def test_valid_boundary_values_are_accepted(self):
        result = enrich_contributor_report(self.issues, self.report,
                                           response_target_hours=0.5,
                                           quiet_days=0)
        self.assertEqual(
            result['team']['health']['response_target']['target_hours'], 0.5)
        self.assertEqual(
            result['team']['health']['quiet_open_backlog']['threshold_days'],
            0)

    def test_input_report_is_not_mutated(self):
        enrich_contributor_report(self.issues, self.report)
        contributor = self.report['contributors'][0]
        self.assertNotIn('health', contributor)


class ResponseTargetTests(unittest.TestCase):
    def setUp(self):
        records = [
            # Response within the 24h target (6h).
            normalized_record(
                number=1, creator='alice', created='2024-01-01T00:00:00Z',
                events=[ev('commented', 'bob', '2024-01-01T06:00:00Z')]),
            # Response after the target (48h).
            normalized_record(
                number=2, creator='bob', created='2024-01-01T00:00:00Z',
                events=[ev('commented', 'alice', '2024-01-03T00:00:00Z')]),
            # No response, and the window is long past the target.
            normalized_record(
                number=3, creator='carol', created='2024-01-01T00:00:00Z',
                events=[]),
        ]
        self.issues, self.report = base_report(records)
        self.result = enrich_contributor_report(self.issues, self.report)

    def test_target_buckets(self):
        target = self.result['team']['health']['response_target']
        self.assertEqual(target['cohort'], 3)
        self.assertEqual(target['recorded_within_target'], 1)
        self.assertEqual(target['recorded_after_target'], 1)
        self.assertEqual(target['no_recorded_response_mature'], 1)
        self.assertEqual(target['still_in_observation'], 0)

    def test_target_evidence(self):
        evidence = self.result['evidence']['response_target']
        self.assertEqual(evidence['recorded_within_target'],
                         ['https://github.com/example/repo/issues/1'])
        self.assertEqual(evidence['no_recorded_response_mature'],
                         ['https://github.com/example/repo/issues/3'])

    def test_still_in_observation_when_window_is_short(self):
        records = [
            normalized_record(
                number=1, creator='alice', created='2024-01-01T00:00:00Z',
                events=[]),
            # A later-dated second issue makes the snapshot reference
            # (2024-01-05) fall after the short window's end.
            normalized_record(
                number=2, creator='alice', created='2024-01-01T00:00:00Z',
                events=[ev('commented', 'bob', '2024-01-05T00:00:00Z')]),
        ]
        issues, report = base_report(
            records, since='2024-01-01T00:00:00Z',
            until='2024-01-01T12:00:00Z')
        result = enrich_contributor_report(issues, report)
        target = result['team']['health']['response_target']
        self.assertEqual(target['cohort'], 2)
        self.assertEqual(target['still_in_observation'], 2)
        self.assertEqual(target['no_recorded_response_mature'], 0)


class AssignmentAndQuietBacklogTests(unittest.TestCase):
    def setUp(self):
        records = [
            # Assigned 2h after creation; reporter alice.
            normalized_record(
                number=1, state='closed', creator='alice',
                created='2024-01-01T00:00:00Z',
                closed='2024-01-02T00:00:00Z',
                events=[ev('assigned', 'alice', '2024-01-01T02:00:00Z',
                           assignee='bob'),
                        ev('commented', 'bob', '2024-01-01T03:00:00Z')]),
            # Old open issue, owned by bob, no participation since creation.
            normalized_record(
                number=2, state='open', creator='carol',
                created='2023-06-01T00:00:00Z', assignees=('bob',),
                events=[]),
            # Old open issue with no owner and no activity.
            normalized_record(
                number=3, state='open', creator='dave',
                created='2023-06-01T00:00:00Z', events=[]),
            # Assignment event without an assignee target.
            normalized_record(
                number=4, state='closed', creator='alice',
                created='2024-01-01T00:00:00Z',
                closed='2024-01-02T00:00:00Z',
                events=[ev('assigned', 'alice', '2024-01-01T01:00:00Z')]),
        ]
        self.issues, self.report = base_report(records)
        self.result = enrich_contributor_report(self.issues, self.report)

    def test_assignment_delay_distribution(self):
        assignment = self.result['team']['health']['first_observed_assignment']
        self.assertEqual(assignment['creation_cohort'], 4)
        self.assertEqual(assignment['samples'], 2)
        self.assertEqual(assignment['median_hours'], 1.5)
        self.assertEqual(assignment['without_observed_assignment'], 2)
        self.assertEqual(
            assignment['observed_assignment_events_missing_target'], 1)

    def test_quiet_open_backlog(self):
        backlog = self.result['team']['health']['quiet_open_backlog']
        self.assertEqual(backlog['issues'], 2)
        self.assertEqual(backlog['without_current_owner'], 1)
        self.assertEqual(backlog['without_activity_reference'], 0)
        self.assertEqual(self.result['evidence']['quiet_open_without_owner'],
                         ['https://github.com/example/repo/issues/3'])

    def test_owner_health_profile(self):
        bob = next(c for c in self.result['contributors']
                   if c['login'] == 'bob')
        health = bob['health']
        self.assertEqual(health['quiet_open_assignments'], 1)
        self.assertEqual(health['open_assignment_age']['samples'], 1)
        self.assertGreater(health['open_assignment_age']['median_days'], 200)
        self.assertEqual(health['sole_external_commenter_issues'], 1)
        self.assertEqual(health['distinct_co_commenters'], 0)

    def test_triage_actions_are_tallied_per_contributor(self):
        alice = next(c for c in self.result['contributors']
                     if c['login'] == 'alice')
        self.assertEqual(alice['health']['triage_actions'], {'assigned': 2})


class WindowHealthTests(unittest.TestCase):
    def test_first_observed_participation_window_flags(self):
        records = [
            normalized_record(
                number=1, creator='alice', created='2023-06-01T00:00:00Z',
                events=[ev('commented', 'bob', '2024-02-01T00:00:00Z'),
                        ev('commented', 'carol', '2024-02-01T00:00:00Z')]),
            # Bob also reported an issue before the window, so his first
            # observed participation predates it.
            normalized_record(
                number=2, creator='bob', created='2023-05-01T00:00:00Z',
                events=[]),
        ]
        issues, report = base_report(records, since='2024-01-01T00:00:00Z',
                                     until='2024-02-01T00:00:00Z')
        result = enrich_contributor_report(issues, report)
        bob = next(c for c in result['contributors'] if c['login'] == 'bob')
        self.assertEqual(bob['health']['first_observed_participation'],
                         '2023-05-01T00:00:00+00:00')
        self.assertIs(bob['health']['recorded_participation_before_window'],
                      True)
        self.assertIs(bob['health']['first_observed_in_selected_window'],
                      False)
        carol = next(c for c in result['contributors']
                     if c['login'] == 'carol')
        self.assertIs(carol['health']['first_observed_in_selected_window'],
                      True)
        self.assertIs(carol['health']['recorded_participation_before_window'],
                      False)

    def test_custom_bot_accounts_are_excluded_from_health(self):
        records = [normalized_record(
            number=1, creator='alice', created='2024-01-01T00:00:00Z',
            assignees=('carol',), state='open',
            events=[ev('commented', 'carol', '2024-01-01T01:00:00Z')])]
        issues, report = base_report(records)
        result = enrich_contributor_report(issues, report,
                                           bot_accounts=('carol',))
        carol = next(c for c in result['contributors']
                     if c['login'] == 'carol')
        self.assertEqual(carol['health']['quiet_open_assignments'], 0)
        self.assertEqual(carol['health']['sole_external_commenter_issues'], 0)


if __name__ == '__main__':
    unittest.main()
