"""Структура utils: доменные пакеты и отсутствие плоских модулей"""

import importlib
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UTILS = PROJECT_ROOT / 'utils'
DOMAINS = {'access', 'capture', 'challenge', 'common', 'device', 'face',
           'stereo', 'storage'}


class ModuleLayoutTests(unittest.TestCase):
    def test_every_utils_module_imports(self):
        modules = sorted(path for path in UTILS.rglob('*.py')
                         if path.name != '__init__.py')
        self.assertGreater(len(modules), 20)
        for path in modules:
            name = '.'.join(path.relative_to(PROJECT_ROOT).with_suffix('').parts)
            with self.subTest(module=name):
                importlib.import_module(name)

    def test_domains_exist_and_are_packages(self):
        for domain in DOMAINS:
            with self.subTest(domain=domain):
                self.assertTrue((UTILS / domain / '__init__.py').is_file())

    def test_no_flat_modules_beyond_paths(self):
        flat = sorted(path.name for path in UTILS.glob('*.py'))
        self.assertEqual(flat, ['paths.py'])


if __name__ == '__main__':
    unittest.main()
