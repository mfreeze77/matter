"""SDK defaults resolve bundled assets independently of a checkout path."""
from pathlib import Path
from unittest.mock import patch
import unittest
from matter.demo import run_fixture
from matter.jsonio import read

ROOT=Path(__file__).resolve().parents[2]

class InstalledAssetsTests(unittest.TestCase):
    def test_default_walkthrough_uses_bundled_schema_when_module_has_no_checkout(self):
        for name in ('oil','civic','diat'):
            fixture=read(ROOT/'examples'/(name+'.json'))
            expected=run_fixture(fixture,schema=read(ROOT/'schemas/walkthrough.schema.json'))
            with patch('matter.demo.__file__','/absent/installed/matter/demo.py'):
                self.assertEqual(run_fixture(fixture),expected)
