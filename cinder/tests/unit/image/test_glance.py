# Copyright 2011 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


import datetime

import glanceclient.exc
import mock
from oslo_config import cfg

from cinder import context
from cinder import exception
from cinder.image import glance
from cinder import test
from cinder.tests.unit.glance import stubs as glance_stubs


CONF = cfg.CONF


class NullWriter(object):
    """Used to test ImageService.get which takes a writer object."""

    def write(self, *arg, **kwargs):
        pass


class TestGlanceSerializer(test.TestCase):
    def test_serialize(self):
        metadata = {'name': 'image1',
                    'is_public': True,
                    'foo': 'bar',
                    'properties': {
                        'prop1': 'propvalue1',
                        'mappings': [
                            {'device': 'bbb'},
                            {'device': 'yyy'}],
                        'block_device_mapping': [
                            {'device_name': '/dev/fake'},
                            {'device_name': '/dev/fake0'}]}}

        converted_expected = {
            'name': 'image1',
            'is_public': True,
            'foo': 'bar',
            'properties': {
                'prop1': 'propvalue1',
                'mappings':
                '[{"device": "bbb"}, '
                '{"device": "yyy"}]',
                'block_device_mapping':
                '[{"device_name": "/dev/fake"}, '
                '{"device_name": "/dev/fake0"}]'}}
        converted = glance._convert_to_string(metadata)
        self.assertEqual(converted, converted_expected)
        self.assertEqual(glance._convert_from_string(converted), metadata)


class TestGlanceImageService(test.TestCase):
    """Tests the Glance image service.

    At a high level, the translations involved are:

        1. Glance -> ImageService - This is needed so we can support
           multiple ImageServices (Glance, Local, etc)

        2. ImageService -> API - This is needed so we can support multple
           APIs (OpenStack, EC2)

    """
    NOW_GLANCE_OLD_FORMAT = "2010-10-11T10:30:22"
    NOW_GLANCE_FORMAT = "2010-10-11T10:30:22.000000"

    class tzinfo(datetime.tzinfo):
        @staticmethod
        def utcoffset(*args, **kwargs):
            return datetime.timedelta()

    NOW_DATETIME = datetime.datetime(2010, 10, 11, 10, 30, 22, tzinfo=tzinfo())

    def setUp(self):
        super(TestGlanceImageService, self).setUp()

        client = glance_stubs.StubGlanceClient()
        self.service = self._create_image_service(client)
        self.context = context.RequestContext('fake', 'fake', auth_token=True)
        self.stubs.Set(glance.time, 'sleep', lambda s: None)

    def _create_image_service(self, client):
        def _fake_create_glance_client(context, netloc, use_ssl, version):
            return client

        self.stubs.Set(glance,
                       '_create_glance_client',
                       _fake_create_glance_client)

        client_wrapper = glance.GlanceClientWrapper('fake', 'fake_host', 9292)
        return glance.GlanceImageService(client=client_wrapper)

    @staticmethod
    def _make_fixture(**kwargs):
        fixture = {'name': None,
                   'properties': {},
                   'status': None,
                   'is_public': None}
        fixture.update(kwargs)
        return fixture

    def _make_datetime_fixture(self):
        return self._make_fixture(created_at=self.NOW_GLANCE_FORMAT,
                                  updated_at=self.NOW_GLANCE_FORMAT,
                                  deleted_at=self.NOW_GLANCE_FORMAT)

    def test_create_with_instance_id(self):
        """Ensure instance_id is persisted as an image-property."""
        fixture = {'name': 'test image',
                   'is_public': False,
                   'properties': {'instance_id': '42', 'user_id': 'fake'}}

        image_id = self.service.create(self.context, fixture)['id']
        image_meta = self.service.show(self.context, image_id)
        expected = {
            'id': image_id,
            'name': 'test image',
            'is_public': False,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted_at': None,
            'deleted': None,
            'status': None,
            'properties': {'instance_id': '42', 'user_id': 'fake'},
            'owner': None,
        }
        self.assertDictMatch(image_meta, expected)

        image_metas = self.service.detail(self.context)
        self.assertDictMatch(image_metas[0], expected)

    def test_create_without_instance_id(self):
        """Test Creating images without instance_id.

        Ensure we can create an image without having to specify an
        instance_id. Public images are an example of an image not tied to an
        instance.
        """
        fixture = {'name': 'test image', 'is_public': False}
        image_id = self.service.create(self.context, fixture)['id']

        expected = {
            'id': image_id,
            'name': 'test image',
            'is_public': False,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted_at': None,
            'deleted': None,
            'status': None,
            'properties': {},
            'owner': None,
        }
        actual = self.service.show(self.context, image_id)
        self.assertDictMatch(actual, expected)

    def test_create(self):
        fixture = self._make_fixture(name='test image')
        num_images = len(self.service.detail(self.context))
        image_id = self.service.create(self.context, fixture)['id']

        self.assertIsNotNone(image_id)
        self.assertEqual(num_images + 1,
                         len(self.service.detail(self.context)))

    def test_create_and_show_non_existing_image(self):
        fixture = self._make_fixture(name='test image')
        image_id = self.service.create(self.context, fixture)['id']

        self.assertIsNotNone(image_id)
        self.assertRaises(exception.ImageNotFound,
                          self.service.show,
                          self.context,
                          'bad image id')

    def test_detail_private_image(self):
        fixture = self._make_fixture(name='test image')
        fixture['is_public'] = False
        properties = {'owner_id': 'proj1'}
        fixture['properties'] = properties

        self.service.create(self.context, fixture)

        proj = self.context.project_id
        self.context.project_id = 'proj1'

        image_metas = self.service.detail(self.context)

        self.context.project_id = proj

        self.assertEqual(1, len(image_metas))
        self.assertEqual(image_metas[0]['name'], 'test image')
        self.assertEqual(image_metas[0]['is_public'], False)

    def test_detail_marker(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.detail(self.context, marker=ids[1])
        self.assertEqual(len(image_metas), 8)
        i = 2
        for meta in image_metas:
            expected = {
                'id': ids[i],
                'status': None,
                'is_public': None,
                'name': 'TestImage %d' % (i),
                'properties': {},
                'size': None,
                'min_disk': None,
                'min_ram': None,
                'disk_format': None,
                'container_format': None,
                'checksum': None,
                'created_at': self.NOW_DATETIME,
                'updated_at': self.NOW_DATETIME,
                'deleted_at': None,
                'deleted': None,
                'owner': None,
            }

            self.assertDictMatch(meta, expected)
            i = i + 1

    def test_detail_limit(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.detail(self.context, limit=5)
        self.assertEqual(len(image_metas), 5)

    def test_detail_default_limit(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.detail(self.context)
        for i, meta in enumerate(image_metas):
            self.assertEqual(meta['name'], 'TestImage %d' % (i))

    def test_detail_marker_and_limit(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.detail(self.context, marker=ids[3], limit=5)
        self.assertEqual(len(image_metas), 5)
        i = 4
        for meta in image_metas:
            expected = {
                'id': ids[i],
                'status': None,
                'is_public': None,
                'name': 'TestImage %d' % (i),
                'properties': {},
                'size': None,
                'min_disk': None,
                'min_ram': None,
                'disk_format': None,
                'container_format': None,
                'checksum': None,
                'created_at': self.NOW_DATETIME,
                'updated_at': self.NOW_DATETIME,
                'deleted_at': None,
                'deleted': None,
                'owner': None,
            }
            self.assertDictMatch(meta, expected)
            i = i + 1

    def test_detail_invalid_marker(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        self.assertRaises(exception.Invalid, self.service.detail,
                          self.context, marker='invalidmarker')

    def test_update(self):
        fixture = self._make_fixture(name='test image')
        image = self.service.create(self.context, fixture)
        image_id = image['id']
        fixture['name'] = 'new image name'
        self.service.update(self.context, image_id, fixture)

        new_image_data = self.service.show(self.context, image_id)
        self.assertEqual('new image name', new_image_data['name'])

    def test_delete(self):
        fixture1 = self._make_fixture(name='test image 1')
        fixture2 = self._make_fixture(name='test image 2')
        fixtures = [fixture1, fixture2]

        num_images = len(self.service.detail(self.context))
        self.assertEqual(0, num_images)

        ids = []
        for fixture in fixtures:
            new_id = self.service.create(self.context, fixture)['id']
            ids.append(new_id)

        num_images = len(self.service.detail(self.context))
        self.assertEqual(2, num_images)

        self.service.delete(self.context, ids[0])

        num_images = len(self.service.detail(self.context))
        self.assertEqual(1, num_images)

    def test_show_passes_through_to_client(self):
        fixture = self._make_fixture(name='image1', is_public=True)
        image_id = self.service.create(self.context, fixture)['id']

        image_meta = self.service.show(self.context, image_id)
        expected = {
            'id': image_id,
            'name': 'image1',
            'is_public': True,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted_at': None,
            'deleted': None,
            'status': None,
            'properties': {},
            'owner': None,
        }
        self.assertEqual(image_meta, expected)

    def test_show_raises_when_no_authtoken_in_the_context(self):
        fixture = self._make_fixture(name='image1',
                                     is_public=False,
                                     properties={'one': 'two'})
        image_id = self.service.create(self.context, fixture)['id']
        self.context.auth_token = False
        self.assertRaises(exception.ImageNotFound,
                          self.service.show,
                          self.context,
                          image_id)

    def test_detail_passes_through_to_client(self):
        fixture = self._make_fixture(name='image10', is_public=True)
        image_id = self.service.create(self.context, fixture)['id']
        image_metas = self.service.detail(self.context)
        expected = [
            {
                'id': image_id,
                'name': 'image10',
                'is_public': True,
                'size': None,
                'min_disk': None,
                'min_ram': None,
                'disk_format': None,
                'container_format': None,
                'checksum': None,
                'created_at': self.NOW_DATETIME,
                'updated_at': self.NOW_DATETIME,
                'deleted_at': None,
                'deleted': None,
                'status': None,
                'properties': {},
                'owner': None,
            },
        ]
        self.assertEqual(image_metas, expected)

    def test_show_makes_datetimes(self):
        fixture = self._make_datetime_fixture()
        image_id = self.service.create(self.context, fixture)['id']
        image_meta = self.service.show(self.context, image_id)
        self.assertEqual(image_meta['created_at'], self.NOW_DATETIME)
        self.assertEqual(image_meta['updated_at'], self.NOW_DATETIME)

    def test_detail_makes_datetimes(self):
        fixture = self._make_datetime_fixture()
        self.service.create(self.context, fixture)
        image_meta = self.service.detail(self.context)[0]
        self.assertEqual(image_meta['created_at'], self.NOW_DATETIME)
        self.assertEqual(image_meta['updated_at'], self.NOW_DATETIME)

    def test_download_with_retries(self):
        tries = [0]

        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            """A client that fails the first time, then succeeds."""
            def get(self, image_id):
                if tries[0] == 0:
                    tries[0] = 1
                    raise glanceclient.exc.ServiceUnavailable('')
                else:
                    return {}

        client = MyGlanceStubClient()
        service = self._create_image_service(client)
        image_id = 1  # doesn't matter
        writer = NullWriter()

        # When retries are disabled, we should get an exception
        self.flags(glance_num_retries=0)
        self.assertRaises(exception.GlanceConnectionFailed,
                          service.download,
                          self.context,
                          image_id,
                          writer)

        # Now lets enable retries. No exception should happen now.
        tries = [0]
        self.flags(glance_num_retries=1)
        service.download(self.context, image_id, writer)

    def test_client_forbidden_converts_to_imagenotauthed(self):
        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            """A client that raises a Forbidden exception."""
            def get(self, image_id):
                raise glanceclient.exc.Forbidden(image_id)

        client = MyGlanceStubClient()
        service = self._create_image_service(client)
        image_id = 1  # doesn't matter
        writer = NullWriter()
        self.assertRaises(exception.ImageNotAuthorized, service.download,
                          self.context, image_id, writer)

    def test_client_httpforbidden_converts_to_imagenotauthed(self):
        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            """A client that raises a HTTPForbidden exception."""
            def get(self, image_id):
                raise glanceclient.exc.HTTPForbidden(image_id)

        client = MyGlanceStubClient()
        service = self._create_image_service(client)
        image_id = 1  # doesn't matter
        writer = NullWriter()
        self.assertRaises(exception.ImageNotAuthorized, service.download,
                          self.context, image_id, writer)

    def test_client_notfound_converts_to_imagenotfound(self):
        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            """A client that raises a NotFound exception."""
            def get(self, image_id):
                raise glanceclient.exc.NotFound(image_id)

        client = MyGlanceStubClient()
        service = self._create_image_service(client)
        image_id = 1  # doesn't matter
        writer = NullWriter()
        self.assertRaises(exception.ImageNotFound, service.download,
                          self.context, image_id, writer)

    def test_client_httpnotfound_converts_to_imagenotfound(self):
        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            """A client that raises a HTTPNotFound exception."""
            def get(self, image_id):
                raise glanceclient.exc.HTTPNotFound(image_id)

        client = MyGlanceStubClient()
        service = self._create_image_service(client)
        image_id = 1  # doesn't matter
        writer = NullWriter()
        self.assertRaises(exception.ImageNotFound, service.download,
                          self.context, image_id, writer)

    @mock.patch('six.moves.builtins.open')
    @mock.patch('shutil.copyfileobj')
    def test_download_from_direct_file(self, mock_copyfileobj, mock_open):
        fixture = self._make_fixture(name='test image',
                                     locations=[{'url': 'file:///tmp/test'}])
        image_id = self.service.create(self.context, fixture)['id']
        writer = NullWriter()
        self.flags(allowed_direct_url_schemes=['file'])
        self.flags(glance_api_version=2)
        self.service.download(self.context, image_id, writer)
        mock_copyfileobj.assert_called_once_with(mock.ANY, writer)

    @mock.patch('six.moves.builtins.open')
    @mock.patch('shutil.copyfileobj')
    def test_download_from_direct_file_non_file(self,
                                                mock_copyfileobj, mock_open):
        fixture = self._make_fixture(name='test image',
                                     direct_url='swift+http://test/image')
        image_id = self.service.create(self.context, fixture)['id']
        writer = NullWriter()
        self.flags(allowed_direct_url_schemes=['file'])
        self.flags(glance_api_version=2)
        self.service.download(self.context, image_id, writer)
        self.assertEqual(None, mock_copyfileobj.call_args)

    def test_glance_client_image_id(self):
        fixture = self._make_fixture(name='test image')
        image_id = self.service.create(self.context, fixture)['id']
        (_service, same_id) = glance.get_remote_image_service(self.context,
                                                              image_id)
        self.assertEqual(same_id, image_id)

    def test_glance_client_image_ref(self):
        fixture = self._make_fixture(name='test image')
        image_id = self.service.create(self.context, fixture)['id']
        image_url = 'http://something-less-likely/%s' % image_id
        (service, same_id) = glance.get_remote_image_service(self.context,
                                                             image_url)
        self.assertEqual(same_id, image_id)
        self.assertEqual(service._client.netloc, 'something-less-likely')
        for ipv6_url in ('[::1]', '::1', '[::1]:444'):
            image_url = 'http://%s/%s' % (ipv6_url, image_id)
            (service, same_id) = glance.get_remote_image_service(self.context,
                                                                 image_url)
            self.assertEqual(same_id, image_id)
            self.assertEqual(service._client.netloc, ipv6_url)

    def test_extracting_missing_attributes(self):
        """Verify behavior from glance objects that are missing attributes

        This fakes the image class and is missing the checksum and name
        attribute as the client would return if they're not set in the
        database. Regression test for bug #1308058.
        """
        class MyFakeGlanceImage(glance_stubs.FakeImage):
            def __init__(self, metadata):
                IMAGE_ATTRIBUTES = ['size', 'disk_format', 'owner',
                                    'container_format', 'id', 'created_at',
                                    'updated_at', 'deleted', 'status',
                                    'min_disk', 'min_ram', 'is_public']
                raw = dict.fromkeys(IMAGE_ATTRIBUTES)
                raw.update(metadata)
                self.__dict__['raw'] = raw

        metadata = {
            'id': 1,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
        }
        image = MyFakeGlanceImage(metadata)
        actual = glance._extract_attributes(image)
        expected = {
            'id': 1,
            'name': None,
            'is_public': None,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted_at': None,
            'deleted': None,
            'status': None,
            'properties': {},
            'owner': None,
        }
        self.assertEqual(actual, expected)

    @mock.patch('cinder.image.glance.CONF')
    def test_extracting_v2_boot_properties(self, config):

        config.glance_api_version = 2
        config.glance_num_retries = 0

        attributes = ['size', 'disk_format', 'owner', 'container_format',
                      'checksum', 'id', 'name', 'created_at', 'updated_at',
                      'deleted', 'status', 'min_disk', 'min_ram', 'is_public']

        metadata = {
            'id': 1,
            'size': 2,
            'min_disk': 2,
            'min_ram': 2,
            'kernel_id': 'foo',
            'ramdisk_id': 'bar',
        }

        class FakeSchema(object):

            def __init__(self, base):
                self.base = base

            def is_base_property(self, key):
                if key in self.base:
                    return True
                else:
                    return False

        image = glance_stubs.FakeImage(metadata)
        client = glance_stubs.StubGlanceClient()

        service = self._create_image_service(client)
        service._image_schema = FakeSchema(attributes)
        actual = service._translate_from_glance(image)
        expected = {
            'id': 1,
            'name': None,
            'is_public': None,
            'size': 2,
            'min_disk': 2,
            'min_ram': 2,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'deleted': None,
            'deleted_at': None,
            'status': None,
            'properties': {'kernel_id': 'foo',
                           'ramdisk_id': 'bar'},
            'owner': None,
            'created_at': None,
            'updated_at': None
        }

        self.assertEqual(expected, actual)


class TestGlanceClientVersion(test.TestCase):
    """Tests the version of the glance client generated."""

    @mock.patch('cinder.image.glance.glanceclient.Client')
    def test_glance_version_by_flag(self, _mockglanceclient):
        """Test glance version set by flag is honoured."""
        glance.GlanceClientWrapper('fake', 'fake_host', 9292)
        self.assertEqual('1', _mockglanceclient.call_args[0][0])
        self.flags(glance_api_version=2)
        glance.GlanceClientWrapper('fake', 'fake_host', 9292)
        self.assertEqual('2', _mockglanceclient.call_args[0][0])
        CONF.reset()

    @mock.patch('cinder.image.glance.glanceclient.Client')
    def test_glance_version_by_arg(self, _mockglanceclient):
        """Test glance version set by arg to GlanceClientWrapper"""
        glance.GlanceClientWrapper('fake', 'fake_host', 9292, version=1)
        self.assertEqual('1', _mockglanceclient.call_args[0][0])
        glance.GlanceClientWrapper('fake', 'fake_host', 9292, version=2)
        self.assertEqual('2', _mockglanceclient.call_args[0][0])

    @mock.patch('cinder.image.glance.glanceclient.Client')
    def test_call_glance_version_by_arg(self, _mockglanceclient):
        """Test glance version set by arg to GlanceClientWrapper"""
        glance_wrapper = glance.GlanceClientWrapper()
        glance_wrapper.call('fake_context', 'method', version=2)

        self.assertEqual('2', _mockglanceclient.call_args[0][0])


def _create_failing_glance_client(info):
    class MyGlanceStubClient(glance_stubs.StubGlanceClient):
        """A client that fails the first time, then succeeds."""
        def get(self, image_id):
            info['num_calls'] += 1
            if info['num_calls'] == 1:
                raise glanceclient.exc.ServiceUnavailable('')
            return {}

    return MyGlanceStubClient()


class TestGlanceImageServiceClient(test.TestCase):

    def setUp(self):
        super(TestGlanceImageServiceClient, self).setUp()
        self.context = context.RequestContext('fake', 'fake', auth_token=True)
        self.stubs.Set(glance.time, 'sleep', lambda s: None)

    def test_create_glance_client(self):
        self.flags(auth_strategy='keystone')
        self.flags(glance_request_timeout=60)

        class MyGlanceStubClient(object):
            def __init__(inst, version, *args, **kwargs):
                self.assertEqual('1', version)
                self.assertEqual("http://fake_host:9292", args[0])
                self.assertTrue(kwargs['token'])
                self.assertEqual(60, kwargs['timeout'])

        self.stubs.Set(glance.glanceclient, 'Client', MyGlanceStubClient)
        client = glance._create_glance_client(self.context, 'fake_host:9292',
                                              False)
        self.assertIsInstance(client, MyGlanceStubClient)

    def test_create_glance_client_auth_strategy_is_not_keystone(self):
        self.flags(auth_strategy='noauth')
        self.flags(glance_request_timeout=60)

        class MyGlanceStubClient(object):
            def __init__(inst, version, *args, **kwargs):
                self.assertEqual('1', version)
                self.assertEqual('http://fake_host:9292', args[0])
                self.assertNotIn('token', kwargs)
                self.assertEqual(60, kwargs['timeout'])

        self.stubs.Set(glance.glanceclient, 'Client', MyGlanceStubClient)
        client = glance._create_glance_client(self.context, 'fake_host:9292',
                                              False)
        self.assertIsInstance(client, MyGlanceStubClient)

    def test_create_glance_client_glance_request_default_timeout(self):
        self.flags(auth_strategy='keystone')
        self.flags(glance_request_timeout=None)

        class MyGlanceStubClient(object):
            def __init__(inst, version, *args, **kwargs):
                self.assertEqual("1", version)
                self.assertEqual("http://fake_host:9292", args[0])
                self.assertTrue(kwargs['token'])
                self.assertNotIn('timeout', kwargs)

        self.stubs.Set(glance.glanceclient, 'Client', MyGlanceStubClient)
        client = glance._create_glance_client(self.context, 'fake_host:9292',
                                              False)
        self.assertIsInstance(client, MyGlanceStubClient)
