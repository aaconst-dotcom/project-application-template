"""White-box tests for config.py."""
import argparse
import json
import os
import unittest

try:
    from tests.helpers import CleanEnvTestCase
except ImportError:  # pragma: no cover
    from helpers import CleanEnvTestCase

import config


class ConvertToTypedValueTests(unittest.TestCase):
    def test_none_passes_through(self):
        self.assertIsNone(config.convert_to_typed_value(None))

    def test_json_number_string_becomes_number(self):
        self.assertEqual(config.convert_to_typed_value('123'), 123)

    def test_json_bool_string_becomes_bool(self):
        self.assertIs(config.convert_to_typed_value('true'), True)

    def test_json_object_string_becomes_dict(self):
        self.assertEqual(config.convert_to_typed_value('{"a": 1}'), {'a': 1})

    def test_plain_string_stays_string(self):
        self.assertEqual(config.convert_to_typed_value('/path/to/data.json'),
                         '/path/to/data.json')

    def test_non_string_passes_through(self):
        self.assertEqual(config.convert_to_typed_value(42), 42)
        value = {'x': [1, 2]}
        self.assertIs(config.convert_to_typed_value(value), value)


class GetParameterTests(CleanEnvTestCase):
    def test_environment_variable_wins(self):
        os.environ['MY_PARAM'] = 'from-env'
        self.assertEqual(config.get_parameter('MY_PARAM'), 'from-env')

    def test_environment_json_prefix_is_decoded(self):
        os.environ['MY_PARAM'] = 'json:{"k": [1, 2]}'
        self.assertEqual(config.get_parameter('MY_PARAM'), {'k': [1, 2]})

    def test_missing_parameter_returns_none(self):
        self.assertIsNone(config.get_parameter('DEFINITELY_MISSING_PARAM'))

    def test_missing_parameter_returns_default(self):
        self.assertEqual(
            config.get_parameter('DEFINITELY_MISSING_PARAM', default='fb'),
            'fb')

    def test_falsy_default_is_not_returned(self):
        # Documented quirk of the implementation: only a truthy default is
        # honoured (`if default:`), so default=0 falls through to None.
        self.assertIsNone(config.get_parameter('DEFINITELY_MISSING_PARAM',
                                               default=0))

    def test_config_file_value_is_used_when_no_env(self):
        (self.tmp / 'config.json').write_text(
            json.dumps({'FILE_PARAM': 'from-file', 'NUM_PARAM': 5}))
        os.chdir(self.tmp)
        config._config = None
        self.assertEqual(config.get_parameter('FILE_PARAM'), 'from-file')
        self.assertEqual(config.get_parameter('NUM_PARAM'), 5)

    def test_env_overrides_config_file(self):
        (self.tmp / 'config.json').write_text(json.dumps({'P': 'file'}))
        os.chdir(self.tmp)
        config._config = None
        os.environ['P'] = 'env'
        self.assertEqual(config.get_parameter('P'), 'env')

    def test_config_is_cached_after_first_load(self):
        (self.tmp / 'config.json').write_text(json.dumps({'P': 'one'}))
        os.chdir(self.tmp)
        config._config = None
        self.assertEqual(config.get_parameter('P'), 'one')
        (self.tmp / 'config.json').write_text(json.dumps({'P': 'two'}))
        # Singleton cache: the file is not re-read.
        self.assertEqual(config.get_parameter('P'), 'one')


class DefaultPathTests(CleanEnvTestCase):
    def test_finds_config_in_current_directory(self):
        (self.tmp / 'config.json').write_text('{}')
        os.chdir(self.tmp)
        self.assertEqual(config._get_default_path(),
                         str(self.tmp / 'config.json'))

    def test_finds_config_in_parent_directory(self):
        (self.tmp / 'config.json').write_text('{}')
        child = self.tmp / 'a' / 'b'
        child.mkdir(parents=True)
        os.chdir(child)
        self.assertEqual(config._get_default_path(),
                         str(self.tmp / 'config.json'))

    def test_returns_none_when_no_config_anywhere(self):
        os.chdir(self.tmp)
        self.assertIsNone(config._get_default_path())


class SetParameterTests(CleanEnvTestCase):
    def test_set_string_parameter_round_trips(self):
        config.set_parameter('ROUND_TRIP', 'hello')
        self.assertEqual(os.environ['ROUND_TRIP'], 'hello')
        self.assertEqual(config.get_parameter('ROUND_TRIP'), 'hello')

    def test_set_non_string_parameter_uses_json_prefix(self):
        config.set_parameter('ROUND_TRIP_NUM', 17)
        self.assertTrue(os.environ['ROUND_TRIP_NUM'].startswith('json:'))
        self.assertEqual(config.get_parameter('ROUND_TRIP_NUM'), 17)

    def test_set_list_parameter_round_trips(self):
        config.set_parameter('ROUND_TRIP_LIST', ['a', 'b'])
        self.assertEqual(config.get_parameter('ROUND_TRIP_LIST'), ['a', 'b'])


class OverwriteFromArgsTests(CleanEnvTestCase):
    def test_non_none_values_are_written(self):
        args = argparse.Namespace(feature=1, label='kind/bug', user=None)
        config.overwrite_from_args(args)
        self.assertEqual(config.get_parameter('feature'), 1)
        self.assertEqual(config.get_parameter('label'), 'kind/bug')
        self.assertNotIn('user', os.environ)

    def test_object_without_vars_is_ignored(self):
        # vars() raises TypeError for a plain object; the function swallows it.
        config.overwrite_from_args(object())
        self.assertIsNone(config.get_parameter('anything'))


if __name__ == '__main__':
    unittest.main()
