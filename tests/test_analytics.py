"""White-box tests for analytics.py (Feature 2 support module)."""
import unittest
from datetime import datetime, timezone

try:
    from tests.helpers import normalized_event, normalized_record
except ImportError:  # pragma: no cover
    from helpers import normalized_event, normalized_record

import analytics
from analytics import (classify, days, enrich, label, normalize, person,
                       select, summary, timestamp)

UTC = timezone.utc


class TimestampTests(unittest.TestCase):
    def test_zulu_timestamp(self):
        self.assertEqual(timestamp('2024-01-01T06:00:00Z'),
                         datetime(2024, 1, 1, 6, tzinfo=UTC))

    def test_naive_timestamp_assumed_utc(self):
        self.assertEqual(timestamp('2024-01-01T06:00:00'),
                         datetime(2024, 1, 1, 6, tzinfo=UTC))

    def test_offset_timestamp_converted_to_utc(self):
        self.assertEqual(timestamp('2024-01-01T06:00:00+02:00'),
                         datetime(2024, 1, 1, 4, tzinfo=UTC))

    def test_non_string_returns_none(self):
        self.assertIsNone(timestamp(None))
        self.assertIsNone(timestamp(12345))
        self.assertIsNone(timestamp(datetime(2024, 1, 1)))

    def test_unparseable_string_returns_none(self):
        self.assertIsNone(timestamp('not a date'))


class PersonLabelTests(unittest.TestCase):
    def test_person_from_string(self):
        self.assertEqual(person('alice'), 'alice')

    def test_person_from_api_dict(self):
        self.assertEqual(person({'login': 'bob'}), 'bob')

    def test_person_from_other_types(self):
        self.assertIsNone(person(None))
        self.assertIsNone(person(42))
        self.assertIsNone(person({'name': 'x'}))

    def test_label_from_string_and_dict(self):
        self.assertEqual(label('kind/bug'), 'kind/bug')
        self.assertEqual(label({'name': 'kind/bug'}), 'kind/bug')
        self.assertEqual(label({'other': 1}), '')

    def test_label_from_number_is_stringified(self):
        self.assertEqual(label(7), '7')


class ClassifyTests(unittest.TestCase):
    def test_single_hit(self):
        self.assertEqual(classify(['kind/bug'], analytics.TYPES), 'bug')
        self.assertEqual(classify(['Severity: Critical'], analytics.SEVERITY),
                         'critical')

    def test_no_hit_is_unknown(self):
        self.assertEqual(classify(['random'], analytics.TYPES), 'unknown')
        self.assertEqual(classify([], analytics.TYPES), 'unknown')

    def test_multiple_hits_are_conflict(self):
        self.assertEqual(classify(['kind/bug', 'kind/task'], analytics.TYPES),
                         'conflict')

    def test_matching_is_case_and_space_insensitive(self):
        self.assertEqual(classify(['  KIND/BUG '], analytics.TYPES), 'bug')


class DaysTests(unittest.TestCase):
    def test_days_between(self):
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 11, 12, tzinfo=UTC)
        self.assertEqual(days(start, end), 10.5)

    def test_days_missing_or_reversed(self):
        start = datetime(2024, 1, 2, tzinfo=UTC)
        end = datetime(2024, 1, 1, tzinfo=UTC)
        self.assertIsNone(days(None, end))
        self.assertIsNone(days(start, None))
        self.assertIsNone(days(start, end))

    def test_days_equal_is_zero(self):
        moment = datetime(2024, 1, 1, tzinfo=UTC)
        self.assertEqual(days(moment, moment), 0.0)


class NormalizeTests(unittest.TestCase):
    def test_non_list_raises_value_error(self):
        with self.assertRaises(ValueError):
            normalize({'a': 1})
        with self.assertRaises(ValueError):
            normalize('nope')

    def test_valid_record_is_normalized(self):
        records, errors = normalize([normalized_record(
            number=5, creator={'login': 'api-user'},
            labels=[{'name': 'kind/bug'}, 'severity: critical'],
            events=[normalized_event('commented', {'login': 'bob'},
                                     '2024-01-02T00:00:00Z', body='hi')])])
        self.assertEqual(errors, [])
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec['number'], 5)
        self.assertEqual(rec['creator'], 'api-user')
        self.assertEqual(rec['labels'], ['kind/bug', 'severity: critical'])
        self.assertEqual(rec['type'], 'bug')
        self.assertEqual(rec['severity'], 'critical')
        self.assertEqual(rec['events'][0]['author'], 'bob')
        self.assertEqual(rec['events'][0]['comment'], 'hi')

    def test_non_object_record_is_reported_and_skipped(self):
        records, errors = normalize(['junk', normalized_record(number=1)])
        self.assertEqual(len(records), 1)
        self.assertEqual(errors, ['Record 1: not an object'])

    def test_pull_request_records_are_skipped_silently(self):
        pr = normalized_record(number=9)
        pr['pull_request'] = {'url': 'https://example.com/pr/9'}
        records, errors = normalize([pr])
        self.assertEqual(records, [])
        self.assertEqual(errors, [])

    def test_non_array_fields_are_reported(self):
        bad = normalized_record(number=1)
        bad['labels'] = 'kind/bug'
        records, errors = normalize([bad])
        self.assertEqual(records, [])
        self.assertEqual(len(errors), 1)
        self.assertIn('must be arrays', errors[0])

    def test_invalid_number_or_state_is_reported(self):
        for bad in (normalized_record(number=0),
                    normalized_record(number=-3),
                    normalized_record(number='x'),
                    normalized_record(state='weird'),
                    normalized_record(state='Open')):
            records, errors = normalize([bad])
            self.assertEqual(records, [])
            self.assertEqual(len(errors), 1)
            self.assertIn('invalid issue number or state', errors[0])

    def test_duplicate_issue_is_reported(self):
        records, errors = normalize([normalized_record(number=1),
                                     normalized_record(number=1)])
        self.assertEqual(len(records), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn('duplicate issue #1', errors[0])

    def test_same_number_in_different_repos_is_not_duplicate(self):
        records, errors = normalize([
            normalized_record(number=1, url='https://github.com/a/x/issues/1'),
            normalized_record(number=1, url='https://github.com/a/y/issues/1')])
        self.assertEqual(len(records), 2)
        self.assertEqual(errors, [])

    def test_duplicate_event_ids_are_deduplicated(self):
        event = normalized_event('commented', 'bob', '2024-01-02T00:00:00Z',
                                 id=99)
        records, _ = normalize([normalized_record(
            number=1, events=[event, dict(event)])])
        self.assertEqual(len(records[0]['events']), 1)

    def test_events_are_sorted_by_date(self):
        records, _ = normalize([normalized_record(number=1, events=[
            normalized_event('commented', 'bob', '2024-01-05T00:00:00Z'),
            normalized_event('commented', 'bob', '2024-01-02T00:00:00Z')])])
        dates = [e['date'] for e in records[0]['events']]
        self.assertEqual(dates, sorted(dates))

    def test_closed_issue_without_closed_date_uses_last_closure_event(self):
        records, _ = normalize([normalized_record(
            number=1, state='closed',
            events=[normalized_event('closed', 'bob', '2024-01-09T00:00:00Z'),
                    normalized_event('closed', 'bob', '2024-01-20T00:00:00Z')])])
        self.assertEqual(records[0]['closed'], '2024-01-20T00:00:00Z')

    def test_closed_issue_with_closed_date_keeps_it(self):
        records, _ = normalize([normalized_record(
            number=1, state='closed', closed='2024-02-01T00:00:00Z',
            events=[normalized_event('closed', 'bob',
                                     '2024-01-20T00:00:00Z')])])
        self.assertEqual(records[0]['closed'], '2024-02-01T00:00:00Z')

    def test_open_issue_closed_date_is_cleared(self):
        records, _ = normalize([normalized_record(
            number=1, state='open', closed='2024-02-01T00:00:00Z')])
        self.assertIsNone(records[0]['closed'])

    def test_missing_title_and_creator_get_defaults(self):
        raw = normalized_record(number=1)
        del raw['title']
        raw['creator'] = None
        records, _ = normalize([raw])
        self.assertEqual(records[0]['title'], '(untitled)')
        self.assertEqual(records[0]['creator'], 'unknown')

    def test_non_dict_events_are_skipped(self):
        records, _ = normalize([normalized_record(
            number=1, events=['junk',
                              normalized_event('commented', 'bob',
                                               '2024-01-02T00:00:00Z')])])
        self.assertEqual(len(records[0]['events']), 1)


class EnrichSelectSummaryTests(unittest.TestCase):
    def setUp(self):
        self.observed = timestamp('2024-06-01T00:00:00Z')
        records, errors = normalize([
            normalized_record(
                number=1, state='open', creator='alice',
                created='2024-01-01T00:00:00Z', labels=('kind/bug',),
                events=[normalized_event('assigned', 'alice',
                                         '2024-01-03T00:00:00Z'),
                        normalized_event('commented', 'bob',
                                         '2024-01-04T00:00:00Z'),
                        normalized_event('reopened', 'bob',
                                         '2024-01-05T00:00:00Z')]),
            normalized_record(
                number=2, state='closed', creator='bob',
                created='2024-01-01T00:00:00Z', closed='2024-01-21T00:00:00Z',
                labels=('kind/task',), assignees=('alice',)),
            normalized_record(
                number=3, state='open', creator='carol',
                created='2024-05-20T00:00:00Z', labels=()),
        ])
        self.assertEqual(errors, [])
        self.issues = records

    def test_enrich_computes_age_assignment_and_counts(self):
        item = enrich(self.issues[0], self.observed)
        self.assertEqual(item['age'], 152.0)  # Jan 1 -> Jun 1 (leap year)
        self.assertEqual(item['assignment_days'], 2.0)
        self.assertEqual(item['comments'], 1)
        self.assertEqual(item['reopened'], 1)
        self.assertNotIn('events', item)
        self.assertNotIn('body', item)

    def test_enrich_closed_issue_age_uses_closure(self):
        item = enrich(self.issues[1], self.observed)
        self.assertEqual(item['age'], 20.0)
        self.assertIsNone(item['assignment_days'])

    def test_select_by_state_type_and_severity(self):
        self.assertEqual(len(select(self.issues, self.observed,
                                    {'state': 'open'})), 2)
        self.assertEqual(len(select(self.issues, self.observed,
                                    {'type': 'bug'})), 1)
        self.assertEqual(len(select(self.issues, self.observed,
                                    {'severity': 'critical'})), 0)

    def test_select_unassigned(self):
        result = select(self.issues, self.observed, {'unassigned': 'true'})
        self.assertEqual([i['number'] for i in result], [1, 3])

    def test_select_age_bands(self):
        old = select(self.issues, self.observed, {'age_band': '90+d'})
        self.assertEqual([i['number'] for i in old], [1])
        young = select(self.issues, self.observed, {'age_band': '8–30d'})
        self.assertEqual([i['number'] for i in young], [3])
        self.assertEqual(select(self.issues, self.observed,
                                {'age_band': 'unknown'}), [])
        self.assertEqual(len(select(self.issues, self.observed,
                                    {'age_band': 'bogus'})), 3)

    def test_select_text_query(self):
        result = select(self.issues, self.observed, {'q': 'CAROL'})
        self.assertEqual([i['number'] for i in result], [3])
        result = select(self.issues, self.observed, {'q': 'issue 2'})
        self.assertEqual([i['number'] for i in result], [2])

    def test_summary_totals_and_stats(self):
        items = select(self.issues, self.observed, {})
        result = summary(items, self.issues, self.observed)
        self.assertEqual(result['total'], 3)
        self.assertEqual(result['open'], 2)
        self.assertEqual(result['closed'], 1)
        self.assertEqual(result['unassigned'], 2)
        self.assertEqual(result['bugs'], 1)
        self.assertEqual(result['closure']['median'], 20.0)
        self.assertEqual(result['assignment']['n'], 1)
        self.assertEqual(result['types'], {'bug': 1, 'task': 1, 'unknown': 1})
        self.assertEqual(result['months']['2024-01']['created'], 2)
        self.assertEqual(result['months']['2024-01']['closed'], 1)
        names = [c['name'] for c in result['contributors']]
        self.assertIn('alice', names)
        self.assertIn('bob', names)

    def test_summary_of_empty_selection(self):
        result = summary([], self.issues, self.observed)
        self.assertEqual(result['total'], 0)
        self.assertIsNone(result['closure']['median'])
        self.assertEqual(result['contributors'], [])


if __name__ == '__main__':
    unittest.main()
