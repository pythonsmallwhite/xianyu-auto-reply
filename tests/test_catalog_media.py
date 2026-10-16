"""Offline tests for cached item media and the actual list serializer."""
import ast
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('catalog_media_under_test', ROOT / 'common/utils/catalog_media.py')
media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)


class CatalogMediaTests(unittest.TestCase):
    def test_personal_and_seller_images(self):
        for payload in ({'pic_info': {'url': '//cdn.example/first.jpg'}}, {'itemImageUrl': 'https://cdn.example/first.jpg'}):
            self.assertEqual(media.extract_catalog_media(payload)['item_images'], ['https://cdn.example/first.jpg'])

    def test_first_image_order_and_duplicates(self):
        result = media.extract_catalog_media({'images': ['/static/1.jpg', '/static/2.jpg', '/static/1.jpg']})
        self.assertEqual(result['item_images'], ['/static/1.jpg', '/static/2.jpg'])

    def test_video_payload_keeps_poster_out_of_image_list(self):
        result = media.extract_catalog_media({'mediaList': [
            {'type': 10000, 'url': 'https://cdn.example/poster.jpg', 'videoUrl': 'https://cdn.example/video.mp4'},
            {'url': 'https://cdn.example/first.jpg'},
        ]})
        self.assertEqual(result['item_video_url'], 'https://cdn.example/video.mp4')
        self.assertEqual(result['item_video_cover'], 'https://cdn.example/poster.jpg')
        self.assertEqual(result['item_images'], ['https://cdn.example/first.jpg'])

    def test_local_video_without_cover(self):
        result = media.extract_catalog_media({'videos': [{'url': '/static/uploads/video.mp4'}]})
        self.assertEqual(result['item_video_url'], '/static/uploads/video.mp4')
        self.assertIsNone(result['item_video_cover'])

    def test_invalid_and_unsafe_media(self):
        for value in (None, '', 'broken-json', [], 42):
            self.assertEqual(media.extract_catalog_media(value)['item_images'], [])
        result = media.extract_catalog_media({'images': ['javascript:alert(1)', 'file:///C:/secret', 'data:text/html,x', 'https://user:password@host/a.jpg', '/static/a.mp4'], 'detail_url': 'https://example/item/1'})
        self.assertEqual(result['item_images'], [])

    def test_detail_json_and_normalized_sync_fields(self):
        detail = {'item_images': ['https://cdn.example/first.jpg'], 'item_video_url': 'https://cdn.example/v.mp4', 'item_video_cover': 'https://cdn.example/c.jpg'}
        self.assertEqual(media.extract_catalog_media({'detail': json.dumps(detail)}), detail)

    def test_media_list_is_bounded(self):
        result = media.extract_catalog_media({'images': [f'/static/{i}.jpg' for i in range(100)]})
        self.assertEqual(len(result['item_images']), 9)

    def test_actual_catalog_serializer(self):
        tree = ast.parse((ROOT / 'common/services/item_service.py').read_text(encoding='utf-8-sig'))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ItemService')
        methods = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in {'_serialize_item', '_format_dt'}]
        test_class = ast.ClassDef(name='Serializer', bases=[], keywords=[], body=methods, decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[test_class], type_ignores=[]))
        scope = {'XYCatalogItem': object, 'datetime': datetime, 'json': json, 'extract_catalog_media': media.extract_catalog_media}
        exec(compile(module, '<actual-item-serializer>', 'exec'), scope)
        item = SimpleNamespace(id=1, item_id='offline-item', title='离线商品', price='1.00', ai_prompt=None, is_polished=False, created_at=None, updated_at=None)
        for detail in ({'pic_info': {'url': '/static/first.jpg'}, 'source': 'seller'}, json.dumps({'pic_info': {'url': '/static/first.jpg'}, 'source': 'seller'})):
            item.metadata_json = {'detail': detail}
            result = scope['Serializer']()._serialize_item(item, 'offline-account')
            self.assertEqual(result['item_images'], ['/static/first.jpg'])
            self.assertTrue(result['is_seller_item'])
            self.assertEqual(result['item_title'], '离线商品')
            self.assertEqual(result['cookie_id'], 'offline-account')


if __name__ == '__main__':
    unittest.main()
