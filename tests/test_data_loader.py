"""White-box tests for data_loader.py (template DataLoader)."""
import io
import unittest
from contextlib import redirect_stdout

try:
    from tests.helpers import CleanEnvTestCase, model_issue
except ImportError:  # pragma: no cover
    from helpers import CleanEnvTestCase, model_issue

import data_loader
from data_loader import DataLoader
from model import State


class DataLoaderTests(CleanEnvTestCase):
    def test_data_path_comes_from_config(self):
        path = self.write_json([model_issue()])
        self.point_loader_at(path)
        loader = DataLoader()
        self.assertEqual(loader.data_path, str(path))

    def test_get_issues_loads_and_converts_records(self):
        path = self.write_json([
            model_issue(number=1, state='open'),
            model_issue(number=2, state='closed'),
        ])
        self.point_loader_at(path)
        with redirect_stdout(io.StringIO()) as out:
            issues = DataLoader().get_issues()
        self.assertEqual([i.number for i in issues], [1, 2])
        self.assertIs(issues[0].state, State.open)
        self.assertIs(issues[1].state, State.closed)
        self.assertIn('Loaded 2 issues from', out.getvalue())

    def test_get_issues_caches_singleton(self):
        path = self.write_json([model_issue(number=1)])
        self.point_loader_at(path)
        with redirect_stdout(io.StringIO()):
            first = DataLoader().get_issues()
            second = DataLoader().get_issues()
        self.assertIs(first, second)

    def test_empty_dataset_loads_as_empty_list(self):
        path = self.write_json([])
        self.point_loader_at(path)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(DataLoader().get_issues(), [])

    def test_missing_file_raises_oserror(self):
        self.point_loader_at(self.tmp / 'does-not-exist.json')
        with self.assertRaises(OSError):
            DataLoader().get_issues()

    def test_invalid_json_raises_value_error(self):
        path = self.tmp / 'broken.json'
        path.write_text('{not json', encoding='utf-8')
        self.point_loader_at(path)
        with self.assertRaises(ValueError):
            DataLoader().get_issues()


class DataLoaderDefectTests(CleanEnvTestCase):
    """Defect-exposing tests (see Team 8 defect report DEFECT-2/DEFECT-3).
    They FAIL against the current code."""

    def test_non_array_json_is_rejected_with_clean_error(self):
        path = self.tmp / 'notalist.json'
        path.write_text('{"a": 1}', encoding='utf-8')
        self.point_loader_at(path)
        try:
            with redirect_stdout(io.StringIO()):
                DataLoader().get_issues()
        except ValueError:
            return  # clean, documented error type
        except Exception as exc:  # noqa: BLE001
            self.fail(
                'Expected a clean ValueError for a non-array data file, '
                f'but got an unhandled {type(exc).__name__}: {exc}')
        self.fail('Expected ValueError for a non-array data file, '
                  'but it was silently accepted')

    def test_unconfigured_data_path_gives_clean_error(self):
        # No ENPM611_PROJECT_DATA_PATH and no config.json anywhere: the
        # loader should say the data path is not configured, not crash
        # inside open() with a TypeError about NoneType.
        import os
        os.chdir(self.tmp)
        loader = DataLoader()
        self.assertIsNone(loader.data_path)
        try:
            with redirect_stdout(io.StringIO()):
                loader.get_issues()
        except (ValueError, OSError) as exc:
            self.assertIn('data', str(exc).lower())
            return
        except Exception as exc:  # noqa: BLE001
            self.fail(
                'Expected a clean error naming the missing data path, '
                f'but got an unhandled {type(exc).__name__}: {exc}')
        self.fail('Expected an error for an unconfigured data path, '
                  'but get_issues() returned normally')


if __name__ == '__main__':
    unittest.main()
