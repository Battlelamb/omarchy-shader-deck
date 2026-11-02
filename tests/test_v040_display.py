"""Saved display preferences stay entirely outside compositor transactions."""
import json
import os
import pathlib
import unittest
from unittest.mock import patch
import test_backend as base
backend=base.backend


class DisplayConfigurationTests(unittest.TestCase):
    home: pathlib.Path
    env: dict
    original: dict
    setUp=base.BackendTests.setUp
    cli=base.BackendTests.cli
    values=base.BackendTests.values

    def test_common_options_validate_roundtrip_reset_and_never_call_ipc(self):
        options={'density':('comfortable',['comfortable','compact']),
                 'layout':('list',['grid','list']),
                 'sortOrder':('default',['default','name','favorites-first'])}
        with patch.dict(os.environ,self.env,clear=True),patch.object(backend,'run_hypr',side_effect=AssertionError('configuration must not call IPC')):
            initial=backend.catalog()
            for key,(default,choices) in options.items():
                self.assertIn(key,initial['settingsSchema'])
                self.assertEqual(initial['settingsSchema'][key]['type'],'enum')
                self.assertEqual(initial['settingsSchema'][key]['choices'],choices)
                self.assertEqual(initial['preferences']['options'][key],default)
                for value in choices:
                    result=backend.preference_command({'options':{key:value}},True)
                    self.assertEqual(result['preferences']['options'][key],value)
            path=self.home/'.config/omarchy/lego'/backend.SLUG/'preferences.json'
            for key in options:
                for value in [True,False,0,1,None,[],{},'unknown','compact\n','😀'*5000]:
                    before=path.read_bytes()
                    with self.assertRaises(ValueError):
                        backend.preference_command({'options':{key:value}},True)
                    self.assertEqual(path.read_bytes(),before)
            backend.preference_command({'reset':True},True)
            for key,(default,_) in options.items():
                self.assertEqual(backend.catalog()['preferences']['options'][key],default)
            legacy=backend.preferences.read(backend.SLUG,backend.PREFERENCE_SCHEMA)
            for key in options:del legacy['options'][key]
            path.write_text(json.dumps(legacy))
            for key,(default,_) in options.items():
                self.assertEqual(backend.catalog()['preferences']['options'][key],default)
        self.assertEqual(self.values(),self.original)
        self.assertFalse((self.home/'state').exists())
        self.assertFalse((self.home/'calls.jsonl').exists())
