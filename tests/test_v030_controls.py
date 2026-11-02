"""Shader syntax/reference controls. Passing these never establishes GPU output."""
import json
import os
import pathlib
import struct
import subprocess
import unittest
from unittest.mock import patch
import test_backend as base
backend=base.backend
RUNTIME=base.RUNTIME


class ShaderControls(unittest.TestCase):
    setUp=base.BackendTests.setUp
    cli=base.BackendTests.cli
    values=base.BackendTests.values

    def test_fixed_and_generated_glsl_compile_with_real_offline_validator_and_negative_control(self):
        validator='/usr/bin/glslangValidator'
        self.assertTrue(os.access(validator,os.X_OK),'Offline GLSL validator prerequisite is missing')
        with patch.dict(os.environ,self.env,clear=True):
            for intensity in (1,50,99,100):
                backend.preferences.change(backend.SLUG,backend.PREFERENCE_SCHEMA,{'options':{'intensity':intensity}})
                for name in backend.SHADERS:
                    path=backend.shader_path('@'+name+'.frag')
                    process=subprocess.run([validator,'-S','frag',path],capture_output=True,timeout=3)
                    self.assertEqual(process.returncode,0,(name,intensity,process.stdout,process.stderr))
        bad=self.home/'invalid.frag';bad.write_text('#version 300 es\nvoid main() { this is invalid GLSL; }\n')
        process=subprocess.run([validator,'-S','frag',str(bad)],capture_output=True,timeout=3)
        self.assertNotEqual(process.returncode,0,'negative GLSL control was incorrectly accepted')

    def test_comparison_png_pixels_are_measured_reference_transforms_not_screenshots(self):
        for name in backend.SHADERS:
            image=RUNTIME/'data/comparisons'/(name+'.png')
            process=subprocess.run(['/usr/bin/magick',str(image),'-depth','8','RGB:-'],capture_output=True,timeout=3)
            self.assertEqual(process.returncode,0,process.stderr)
            self.assertEqual(len(process.stdout),640*320*3)
            def pixel(x,y):
                start=(y*640+x)*3
                return tuple(process.stdout[start:start+3])
            self.assertEqual(pixel(20,100),(225,55,55))
            r,g,b=225/255,55/255,55/255
            if name=='dim':after=[r*.65,g*.65,b*.65]
            elif name=='cool':after=[r*.90,g*.97,b]
            elif name=='warm':after=[r,g*.96,b*.88]
            elif name=='softcontrast':after=[(v-.5)*.75+.5 for v in (r,g,b)]
            elif name=='sepia':after=[r*.393+g*.769+b*.189,r*.349+g*.686+b*.168,r*.272+g*.534+b*.131]
            else:after=[r*.2126+g*.7152+b*.0722]*3
            self.assertEqual(pixel(340,100),tuple(round(min(1,max(0,v))*255) for v in after))

    def test_intensity_invalid_options_and_unknown_favorites_never_authorize_ipc(self):
        self.assertEqual(self.cli('preferences','--apply','--payload','{"favorites":["arbitrary.frag"]}')[0],0)
        path=next((self.home/'.config').rglob('preferences.json'))
        saved=path.read_bytes()
        for value in (-1,101,True,False,1.5,'50',None,[],{}):
            payload=json.dumps({'options':{'intensity':value}})
            self.assertNotEqual(self.cli('preferences','--apply','--payload',payload)[0],0)
            self.assertEqual(path.read_bytes(),saved)
        for ident,verb in [('../cool.frag','apply'),('arbitrary.frag','favorite'),('restore:last','preview'),('cool','import')]:
            self.assertNotEqual(self.cli('action','--id',ident,'--verb',verb,'--apply')[0],0)
        self.assertFalse((self.home/'calls.jsonl').exists())
        self.assertEqual(self.values(),self.original)

    def test_payload_parser_shared_boundaries_remain_strict(self):
        for raw in ['{"intensity":1,"intensity":2}','{"x":NaN}','{"x":1e999}','[]',
                    '{"x":'+'['*100+'0'+']'*100+'}',json.dumps({'x':'😀'*5000},ensure_ascii=False)]:
            with self.subTest(raw=raw[:80]),self.assertRaises(ValueError):
                backend.parse_payload(raw)
