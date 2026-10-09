"""Dataset integrity, leakage and metric regression; no real desktop capture."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.validate_real_dataset import validate_manifest, align_tiles, aggregate, main
from scripts.collect_real_dataset import add_image


class DatasetIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'image.png').write_bytes(b'fixture-bytes')
        self.sample = {'id':'one','session_id':'game-1','split':'development','status':'reviewed',
                       'source':{'kind':'local_capture','provenance':'fixture','used_for_tuning':True},
                       'image':'image.png','sha256':hashlib.sha256(b'fixture-bytes').hexdigest(),
                       'size':[100,100],'hand':{'roi':[0,.5,1,1],'tiles':[4,34,31,-1]},
                       'buttons':{'roi':[0,0,1,.5],'visible':[]},'reviewer':'test'}
        self.path=self.root/'manifest.json'

    def write(self, samples):
        self.path.write_text(json.dumps({'schema_version':1,'samples':samples}), encoding='utf-8')

    def test_valid_reviewed_development(self):
        self.write([self.sample]); self.assertEqual(len(validate_manifest(self.path)['samples']),1)

    def test_tuned_sample_cannot_be_test(self):
        self.sample['split']='test'; self.write([self.sample])
        with self.assertRaisesRegex(ValueError,'unused'):
            validate_manifest(self.path)

    def test_session_split_leakage_rejected(self):
        other=copy.deepcopy(self.sample); other.update(id='two',split='test')
        other['source']['used_for_tuning']=False
        self.write([self.sample,other])
        with self.assertRaisesRegex(ValueError,'session leaks'):
            validate_manifest(self.path)

    def test_duplicate_content_rejected(self):
        other=copy.deepcopy(self.sample); other.update(id='two',session_id='game-2')
        self.write([self.sample,other])
        with self.assertRaisesRegex(ValueError,'duplicate image'):
            validate_manifest(self.path)

    def test_image_tampering_rejected(self):
        self.write([self.sample]); (self.root/'image.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'SHA256'):
            validate_manifest(self.path)

    def test_bad_roi_and_invalid_white_label_rejected(self):
        self.sample['hand']['roi']=[0,0,2,1]; self.write([self.sample])
        with self.assertRaisesRegex(ValueError,'ROI'):
            validate_manifest(self.path)
        self.sample['hand']['roi']=[0,0,1,1]; self.sample['hand']['tiles']=[37]; self.write([self.sample])
        with self.assertRaisesRegex(ValueError,'tile IDs'):
            validate_manifest(self.path)

    def test_missing_label_cannot_be_reviewed(self):
        self.sample.pop('buttons'); self.sample['hand']['tiles']=None; self.write([self.sample])
        with self.assertRaisesRegex(ValueError,'explicit labels'):
            validate_manifest(self.path)

    def test_empty_test_split_is_not_successful_evaluation(self):
        self.write([self.sample])
        self.assertEqual(main(['--manifest',str(self.path)]),2)


class MetricTests(unittest.TestCase):
    def row(self, expected, predicted, **kwargs):
        return dict(expected_hand=expected,predicted_hand=predicted,elapsed_ms=10,**kwargs)

    def test_extra_tile_cannot_pass_exact_or_sequence(self):
        result=aggregate([self.row([0,1],[0,1,2])])
        self.assertEqual(result['exact_hand_rate'],0)
        self.assertEqual(result['counts']['extra_detections'],1)
        self.assertLess(result['sequence_accuracy'],1)

    def test_red_downgrade_and_white_rejection_are_errors(self):
        result=aggregate([self.row([34,31,-1],[4,-1,2])])
        self.assertEqual(result['tile_accuracy'],0)
        self.assertEqual(result['known_tile_rejection_rate'],.5)
        self.assertEqual(result['counts']['back_false_accepts'],1)

    def test_missing_tile_counts_as_rejection(self):
        result=aggregate([self.row([0,1],[0])])
        self.assertEqual(result['known_tile_rejection_rate'],.5)

    def test_button_negative_frame_false_positive(self):
        result=aggregate([dict(expected_buttons=[],predicted_buttons=['ron'],elapsed_ms=3)])
        self.assertEqual(result['negative_button_frame_fp_rate'],1)
        self.assertAlmostEqual(result['button_false_positive_rate'],1/7)

    def test_no_data_is_null_not_perfect_or_zero(self):
        result=aggregate([])
        self.assertIsNone(result['tile_accuracy']); self.assertIsNone(result['latency_ms']['p95'])

    def test_alignment_handles_duplicate_tiles(self):
        pairs, edits=align_tiles([4,4,4],[4,4])
        self.assertEqual(edits,1)
        self.assertEqual(sum(gt==pred for gt,pred in pairs),2)


class CollectionTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.source=self.root/'source.png'
        Image.new('RGB',(100,100),(10,20,30)).save(self.source)
        self.manifest=self.root/'dataset/manifest.json'

    def test_import_preserves_bytes_and_starts_pending(self):
        add_image(self.manifest,self.source,'new-game','test','new local screenshot')
        sample=validate_manifest(self.manifest)['samples'][0]
        self.assertEqual(sample['status'],'pending')
        self.assertIsNone(sample['hand']['tiles'])
        self.assertEqual(sample['_image_path'].read_bytes(),self.source.read_bytes())

    def test_reimport_cannot_inflate_sample_count(self):
        add_image(self.manifest,self.source,'game-1','development','local')
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            add_image(self.manifest,self.source,'game-2','development','local')
        self.assertEqual(len(validate_manifest(self.manifest)['samples']),1)

    def test_import_tuned_test_and_empty_session_rejected(self):
        with self.assertRaisesRegex(ValueError,'unused'):
            add_image(self.manifest,self.source,'game-1','test','local',True)
        with self.assertRaisesRegex(ValueError,'session'):
            add_image(self.manifest,self.source,'','development','local')


if __name__=='__main__':
    unittest.main()
