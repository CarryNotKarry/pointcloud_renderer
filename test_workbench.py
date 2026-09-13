"""Regression checks for comparison fairness and exact ROI crops; no GPU needed."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from workbench_core import Workspace, roi_pixels


class WorkbenchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.w = Workspace(self.root/"workspace")
        points = np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1],[1,1,1]], dtype=float)
        for name in ("Input", "GT"):
            d = self.root/name
            d.mkdir()
            np.savetxt(d/"sample.xyz", points[:4] if name == "Input" else points)
        self.w.setup([dict(name=n, directory=str(self.root/n)) for n in ("Input", "Missing", "GT")])

    def tearDown(self):
        self.tmp.cleanup()

    def test_camera_and_radius_do_not_change_when_hiding_method(self):
        clouds = self.w.clouds("sample.xyz")
        cfg = self.w.config("sample.xyz", 128)
        camera = self.w.camera("sample.xyz", cfg, clouds)
        obj = self.w.session["objects"]["sample.xyz"]
        radius = obj["radius"]
        methods = self.w.session["methods"]
        methods[2]["visible"] = False
        self.w.update(dict(methods=methods))
        self.assertEqual(camera, self.w.camera("sample.xyz", cfg, self.w.clouds("sample.xyz")))
        self.assertEqual(radius, obj["radius"])

    def test_roundtrip_and_camera_metadata(self):
        roi = dict(x=.25, y=.125, w=.125, h=.25)
        self.w.update(dict(target="sample.xyz", object=dict(rois=[roi])))
        path = self.w.camera_file("sample.xyz")["path"]
        before = self.w.session["objects"]["sample.xyz"]["camera"]
        other = Workspace(self.root/"reopened")
        other.load(self.w.session_path)
        self.assertEqual(other.session["objects"]["sample.xyz"]["rois"], [roi])
        other.camera_file("sample.xyz", path, load=True)
        self.assertEqual(other.session["objects"]["sample.xyz"]["camera"], before)

    def test_export_crops_clean_pixels_and_keeps_missing_column(self):
        roi = dict(x=.25, y=.125, w=.25, h=.25)
        self.w.update(dict(target="sample.xyz", object=dict(rois=[roi])))
        def fake_render(points, path, **kwargs):
            size = kwargs["config"].width
            yy, xx = np.mgrid[:size,:size]
            data = np.stack((xx % 256, yy % 256, np.full_like(xx, 80)), axis=2).astype('uint8')
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(data).save(path)
            return data
        with patch('workbench_core.render_point_cloud', fake_render):
            result = self.w.export(size=256, cell=128, pdf=False)
        manifest = json.loads((Path(result['directory'])/'manifest.json').read_text())
        methods = manifest['objects'][0]['methods']
        self.assertEqual([m['name'] for m in methods], ['Input','Missing','GT'])
        self.assertEqual(methods[1]['status'], 'missing')
        for method in (methods[0], methods[2]):
            single = Image.open(method['single'])
            crop = Image.open(method['crops'][0]['path'])
            self.assertTrue(np.array_equal(np.asarray(crop), np.asarray(single.crop((64,32,128,96)))))
            self.assertEqual(method['crops'][0]['pixels'], [64,32,128,96])

    def test_invalid_roi_rejected_before_mutation(self):
        with self.assertRaises(ValueError):
            self.w.update(dict(target='sample.xyz', object=dict(rois=[dict(x=.9,y=0,w=.2,h=.2)])))
        self.assertEqual(self.w.session['objects']['sample.xyz']['rois'], [])
        self.assertEqual(roi_pixels(dict(x=0,y=0,w=1,h=1),1600,1600),(0,0,1600,1600))

    def test_undo_restores_deleted_roi_after_session_reload(self):
        roi = dict(x=.2,y=.3,w=.2,h=.1)
        self.w.update(dict(target='sample.xyz',object=dict(rois=[roi])))
        self.w.update(dict(target='sample.xyz',object=dict(rois=[])))
        w = Workspace(self.root/'reload')
        w.load(self.w.session_path)
        w.undo_rois('sample.xyz')
        self.assertEqual(w.session['objects']['sample.xyz']['rois'],[roi])
        w.undo_rois('sample.xyz')
        self.assertEqual(w.session['objects']['sample.xyz']['rois'],[])

    def test_interactive_camera_is_used_exactly(self):
        clouds=self.w.clouds('sample.xyz')
        cfg=self.w.config('sample.xyz',480)
        camera=self.w.camera('sample.xyz',cfg,clouds)
        from dataclasses import asdict
        edited=asdict(camera)
        edited['position']=[3.,-3.,2.]
        edited['parallel_scale']=.55
        self.w.update(dict(target='sample.xyz',object=dict(camera=edited,azimuth=-45)))
        self.assertEqual(self.w.camera('sample.xyz',cfg,clouds).parallel_scale,.55)
        self.assertEqual(list(self.w.camera('sample.xyz',cfg,clouds).position),[3.,-3.,2.])
        bad={**edited,'parallel_scale':float('nan')}
        with self.assertRaises(ValueError):
            self.w.update(dict(target='sample.xyz',object=dict(camera=bad)))
        self.assertEqual(self.w.session['objects']['sample.xyz']['camera'],edited)

    def test_individual_pdf_jpg_png_and_progress(self):
        rois=[dict(x=.25,y=.125,w=.25,h=.25),dict(x=.1,y=.5,w=.4,h=.2)]
        self.w.update(dict(target='sample.xyz',object=dict(rois=rois)))
        def fake_render(points,path,**kwargs):
            n=kwargs['config'].width
            yy,xx=np.mgrid[:n,:n]
            image=Image.fromarray(np.stack((xx,yy,xx*0+120),axis=2).astype('uint8'))
            Path(path).parent.mkdir(parents=True,exist_ok=True)
            image.save(path)
            return np.asarray(image)
        progress=self.root/'progress.json'
        with patch('workbench_core.render_point_cloud',fake_render):
            result=self.w.export_assets(size=256,progress_path=progress)
        root=Path(result['directory'])
        m=json.loads((root/'manifest.json').read_text())
        self.assertEqual(result['file_count'],12)
        self.assertFalse((root/'comparison.pdf').exists())
        self.assertTrue((root/'assets.zip').is_file())
        p=json.loads(progress.read_text())
        self.assertEqual(p['completed'],p['total'])
        for asset in m['files']:
            self.assertEqual(set(asset['files']),{'png','jpg','pdf'})
            self.assertEqual((root/asset['files']['pdf']).read_bytes()[:4],b'%PDF')
            with Image.open(root/asset['files']['png']) as png, Image.open(root/asset['files']['jpg']) as jpg:
                self.assertEqual(png.size,jpg.size)
        for method in m['objects'][0]['methods']:
            if method.get('status')=='missing':continue
            clean=Image.open(root/method['clean']['png'])
            for crop in method['crops']:
                actual=Image.open(root/crop['clean']['png'])
                self.assertTrue(np.array_equal(np.asarray(actual),np.asarray(clean.crop(crop['pixels']))))
        saved=json.loads((root/'session.json').read_text())
        self.assertEqual(saved['export_settings']['size'],256)
        self.assertEqual(saved['objects']['sample.xyz']['rois'],rois)


if __name__ == '__main__':
    unittest.main()
