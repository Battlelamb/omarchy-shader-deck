"""Scene selection changes only fixed full-strength CPU reference charts."""
import json
import os
import pathlib
import subprocess
import unittest
from unittest.mock import patch
import test_backend as base
backend=base.backend
RUNTIME=base.RUNTIME


class SceneTests(unittest.TestCase):
    home: pathlib.Path
    env: dict
    original: dict
    setUp=base.BackendTests.setUp
    cli=base.BackendTests.cli
    values=base.BackendTests.values

    def test_scene_selects_reference_chart_without_ipc_or_strength_changes(self):
        with patch.dict(os.environ,self.env,clear=True),patch.object(backend,'run_hypr',side_effect=AssertionError('reference must not call IPC')):
            initial=backend.catalog()
            self.assertIn('comparisonScene',initial['settingsSchema'])
            self.assertEqual(initial['preferences']['options']['comparisonScene'],'color-bars')
            for scene in ['color-bars','grayscale-ramp']:
                backend.preference_command({'options':{'comparisonScene':scene,'intensity':37}},True)
                rows={r['id']:r for r in backend.catalog()['rows']}
                for name in backend.SHADERS:
                    compared=backend.action(name,'compare')
                    path=pathlib.Path(compared['preview'])
                    self.assertTrue(path.is_file())
                    self.assertEqual(compared['preview'],rows[name]['preview'])
                    expected=RUNTIME/'data/comparisons'
                    if scene!='color-bars':expected=expected/scene
                    self.assertEqual(path,expected/(name+'.png'))
                    self.assertIn(scene,compared['detail'])
                    self.assertIn('100%',compared['detail'])
                    self.assertIn('not a compositor/GPU capture',compared['detail'])
                self.assertEqual(backend.preferences.read(backend.SLUG,backend.PREFERENCE_SCHEMA)['options']['intensity'],37)
        self.assertEqual(self.values(),self.original)
        self.assertFalse((self.home/'state').exists())
        self.assertFalse((self.home/'calls.jsonl').exists())

    def test_grayscale_scene_uses_existing_independent_reference_pixel_oracle(self):
        with patch.dict(os.environ,self.env,clear=True):
            backend.preference_command({'options':{'comparisonScene':'grayscale-ramp'}},True)
            for name in backend.SHADERS:
                path=backend.action(name,'compare')['preview']
                decoded=subprocess.run(['/usr/bin/magick',path,'-depth','8','RGB:-'],capture_output=True,timeout=3)
                self.assertEqual(decoded.returncode,0,decoded.stderr)
                self.assertEqual(len(decoded.stdout),640*320*3)
                def pixel(x,y):
                    start=(y*640+x)*3
                    return tuple(decoded.stdout[start:start+3])
                for x,v in [(20,0),(84,64),(148,128),(212,192),(276,255)]:
                    self.assertEqual(pixel(x,100),(v,v,v))
                    r=g=b=v/255
                    if name=='dim':after=[r*.65,g*.65,b*.65]
                    elif name=='cool':after=[r*.90,g*.97,b]
                    elif name=='warm':after=[r,g*.96,b*.88]
                    elif name=='softcontrast':after=[(v-.5)*.75+.5 for v in (r,g,b)]
                    elif name=='sepia':after=[r*.393+g*.769+b*.189,r*.349+g*.686+b*.168,r*.272+g*.534+b*.131]
                    else:after=[r*.2126+g*.7152+b*.0722]*3
                    self.assertEqual(pixel(x+320,100),tuple(round(min(1,max(0,v))*255) for v in after))

    def test_scene_configuration_is_strict_atomic_and_does_not_change_shader_programs(self):
        original={p:p.read_bytes() for p in (RUNTIME/'data/shaders').glob('*.frag')}
        with patch.dict(os.environ,self.env,clear=True),patch.object(backend,'run_hypr',side_effect=AssertionError('configuration must not call IPC')):
            backend.preference_command({'options':{'comparisonScene':'grayscale-ramp'}},True)
            path=self.home/'.config/omarchy/lego/shader-deck/preferences.json'
            saved=path.read_bytes()
            for value in [True,0,None,[],{},'../grayscale','color-bars\n']:
                with self.assertRaises(ValueError):backend.preference_command({'options':{'comparisonScene':value}},True)
                self.assertEqual(path.read_bytes(),saved)
            backend.preference_command({'reset':True},True)
            self.assertEqual(backend.catalog()['preferences']['options']['comparisonScene'],'color-bars')
        self.assertEqual({p:p.read_bytes() for p in original},original)
        self.assertFalse((self.home/'calls.jsonl').exists())
        self.assertFalse((self.home/'state').exists())
