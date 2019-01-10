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
import itertools
import six

import ddt
import glanceclient.exc
from keystoneauth1.loading import session as ks_session
from keystoneauth1 import session
import mock
from oslo_config import cfg

from cinder import context
from cinder import exception
from cinder.image import glance
from cinder import service_auth
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
                    'visibility': 'public',
                    'protected': True,
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
            'visibility': 'public',
            'protected': True,
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
        self.assertEqual(converted_expected, converted)
        self.assertEqual(metadata, glance._convert_from_string(converted))


@ddt.ddt
class TestGlanceImageService(test.TestCase):
    """Tests the Glance image service.

    At a high level, the translations involved are:

        1. Glance -> ImageService - This is needed so we can support
           multiple ImageServices (Glance, Local, etc)

        2. ImageService -> API - This is needed so we can support multiple
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
        service_catalog = [{u'type': u'image', u'name': u'glance',
                            u'endpoints': [{
                                u'publicURL': u'http://example.com:9292'}]}]
        self.service = self._create_image_service(client)
        self.context = context.RequestContext('fake', 'fake', auth_token=True)
        self.context.service_catalog = service_catalog
        self.mock_object(glance.time, 'sleep', return_value=None)

    def _create_image_service(self, client):
        def _fake_create_glance_client(context, netloc, use_ssl):
            return client

        self.mock_object(glance, '_create_glance_client',
                         _fake_create_glance_client)

        client_wrapper = glance.GlanceClientWrapper('fake', 'fake_host', 9292)
        return glance.GlanceImageService(client=client_wrapper)

    @staticmethod
    def _make_fixture(**kwargs):
        fixture = {'name': None,
                   'properties': {},
                   'status': None,
                   'visibility': None,
                   'protected': None}
        fixture.update(kwargs)
        return fixture

    @staticmethod
    def _make_image_member_fixtures(**kwargs):
        fixtures = []
        fixture = {'status': None,
                   'image_id': None,
                   'member_id': None,
                   'created_at': '2018-03-14T21:48:13Z',
                   'updated_at': '2018-03-14T21:50:51Z',
                   'schema': '/v2/schemas/member'}
        fixture.update(kwargs)
        fixtures.append(fixture)
        return fixtures

    def _make_datetime_fixture(self):
        return self._make_fixture(created_at=self.NOW_GLANCE_FORMAT,
                                  updated_at=self.NOW_GLANCE_FORMAT,
                                  deleted_at=self.NOW_GLANCE_FORMAT)

    def test_list_members(self):
        fixture = {'status': None,
                   'image_id': None,
                   'member_id': None,
                   'created_at': '2018-03-14T21:48:13Z',
                   'updated_at': '2018-03-14T21:50:51Z',
                   'schema': '/v2/schemas/member'}
        image_id = '97c1ef11-3a64-4756-9f8c-7f9fb5abe09f'
        member_id = '50fcc79f25524744a2c34682a1a74914'
        fixture['status'] = 'accepted'
        fixture['image_id'] = image_id
        fixture['member_id'] = member_id
        with mock.patch.object(self.service, '_client') as client_mock:
            client_mock.call.return_value = self._make_image_member_fixtures(
                image_id=image_id, member_id=member_id, status='accepted')
            result = self.service.list_members(self.context, image_id)
        self.assertEqual([fixture], result)
        client_mock.call.assert_called_once_with(self.context,
                                                 'list',
                                                 controller='image_members',
                                                 image_id=image_id)

    def test_get_api_servers(self):
        result = glance.get_api_servers(self.context)
        expected = (u'example.com:9292', False)
        self.assertEqual(expected, next(result))

    def test_get_api_servers_not_mounted_at_root_and_ssl(self):
        service_catalog = [{u'type': u'image', u'name': u'glance',
                            u'endpoints': [{
                                u'publicURL': u'https://example.com/image'}]}]
        self.context = context.RequestContext('fake', 'fake', auth_token=True)
        self.context.service_catalog = service_catalog
        result = glance.get_api_servers(self.context)
        expected = (u'example.com/image', True)
        self.assertEqual(expected, next(result))

    def test_create_with_instance_id(self):
        """Ensure instance_id is persisted as an image-property."""
        fixture = {'name': 'test image',
                   'is_public': False,
                   'protected': False,
                   'properties': {'instance_id': '42', 'user_id': 'fake'}}

        image_id = self.service.create(self.context, fixture)['id']
        image_meta = self.service.show(self.context, image_id)
        expected = {
            'id': image_id,
            'name': 'test image',
            'protected': False,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted': None,
            'status': None,
            'properties': {'instance_id': '42', 'is_public': False,
                           'user_id': 'fake'},
            'owner': None,
            'visibility': None,
        }
        self.assertDictEqual(expected, image_meta)

        image_metas = self.service.detail(self.context)
        self.assertDictEqual(expected, image_metas[0])

    def test_create_without_instance_id(self):
        """Test Creating images without instance_id.

        Ensure we can create an image without having to specify an
        instance_id. Public images are an example of an image not tied to an
        instance.
        """
        fixture = {'name': 'test image', 'is_public': False,
                   'protected': False}
        image_id = self.service.create(self.context, fixture)['id']

        expected = {
            'id': image_id,
            'name': 'test image',
            'protected': False,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted': None,
            'status': None,
            'properties': {'is_public': False},
            'owner': None,
            'visibility': None,
        }
        actual = self.service.show(self.context, image_id)
        self.assertDictEqual(expected, actual)

    def test_show_shared_image_membership_success(self):
        """Test Create Shared Image Membership Success

        Ensure we can get access to a shared image
        """
        fixture = {'name': 'test image', 'is_public': False,
                   'protected': False, 'visibility': 'shared'}
        # pid = self.context.project_id
        image_id = self.service.create(self.context, fixture)['id']
        image = {
            'id': image_id,
            'name': 'test image',
            'protected': False,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted': None,
            'status': None,
            'properties': {'is_public': False},
            'owner': None,
            'visibility': None,
        }
        member_id = '50fcc79f25524744a2c34682a1a74914'
        with mock.patch.object(self.service, '_client') as client_mock:
            with mock.patch.object(
                    self.service, '_translate_from_glance') as tg_mock:
                tg_mock.return_value = {}
                mock_image = mock.Mock()
                mock_image.is_public = False
                mock_image.properties = {'is_public': False}
                mock_image.visibility = 'shared'
                mock_image.keys.return_value = image.keys()
                client_mock.call.side_effect = [
                    mock_image,
                    self._make_image_member_fixtures(image_id=image_id,
                                                     member_id=member_id,
                                                     status='accepted')]
                self.context.project_id = member_id
                self.context.is_admin = False
                self.context.user_id = image_id
                self.context.auth_token = False
                self.service.show(self.context, image_id)

    def test_show_shared_image_membership_fail_status(self):
        """Test Create Shared Image Membership Failure

        Ensure we can't get access to a shared image with the wrong membership
        status (in this case 'pending')
        """
        fixture = {'name': 'test image', 'is_public': False,
                   'protected': False, 'visibility': 'shared'}
        # pid = self.context.project_id
        image_id = self.service.create(self.context, fixture)['id']
        image = {
            'id': image_id,
            'name': 'test image',
            'protected': False,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted': None,
            'status': None,
            'properties': {'is_public': False},
            'owner': None,
            'visibility': None,
        }
        member_id = '50fcc79f25524744a2c34682a1a74914'
        with mock.patch.object(self.service, '_client') as client_mock:
            with mock.patch.object(
                    self.service, '_translate_from_glance') as tg_mock:
                tg_mock.return_value = {}
                mock_image = mock.Mock()
                mock_image.is_public = False
                mock_image.properties = {'is_public': False}
                mock_image.visibility = 'shared'
                mock_image.keys.return_value = image.keys()
                client_mock.call.side_effect = [
                    mock_image,
                    self._make_image_member_fixtures(image_id=image_id,
                                                     member_id=member_id,
                                                     status='pending')]
                self.context.project_id = member_id
                self.context.is_admin = False
                self.context.user_id = image_id
                self.context.auth_token = False
                self.assertRaises(exception.ImageNotFound,
                                  self.service.show,
                                  self.context,
                                  image_id)

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
        fixture['visibility'] = 'private'
        fixture['protected'] = False
        properties = {'owner_id': 'proj1'}
        fixture['properties'] = properties

        self.service.create(self.context, fixture)

        proj = self.context.project_id
        self.context.project_id = 'proj1'

        image_metas = self.service.detail(self.context)

        self.context.project_id = proj

        self.assertEqual(1, len(image_metas))
        self.assertEqual('test image', image_metas[0]['name'])
        self.assertEqual('private', image_metas[0]['visibility'])

    def test_detail_v2(self):
        """Check we don't send is_public key by default with Glance v2."""
        with mock.patch.object(self.service, '_client') as client_mock:
            client_mock.return_value = []
            result = self.service.detail(self.context)
        self.assertListEqual([], result)
        client_mock.call.assert_called_once_with(self.context, 'list')

    def test_detail_marker(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.detail(self.context, marker=ids[1])
        self.assertEqual(8, len(image_metas))
        i = 2
        for meta in image_metas:
            expected = {
                'id': ids[i],
                'status': None,
                'protected': None,
                'name': 'TestImage %d' % (i),
                'properties': {'properties': {}},
                'size': None,
                'min_disk': None,
                'min_ram': None,
                'disk_format': None,
                'container_format': None,
                'checksum': None,
                'created_at': self.NOW_DATETIME,
                'updated_at': self.NOW_DATETIME,
                'deleted': None,
                'owner': None,
                'visibility': None,
            }

            self.assertDictEqual(expected, meta)
            i = i + 1

    def test_detail_limit(self):
        fixtures = []
        ids = []
        for i in range(10):
            fixture = self._make_fixture(name='TestImage %d' % (i))
            fixtures.append(fixture)
            ids.append(self.service.create(self.context, fixture)['id'])

        image_metas = self.service.detail(self.context, limit=5)
        self.assertEqual(5, len(image_metas))

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
        self.assertEqual(5, len(image_metas))
        i = 4
        for meta in image_metas:
            expected = {
                'id': ids[i],
                'status': None,
                'protected': None,
                'name': 'TestImage %d' % (i),
                'properties': {'properties': {}},
                'size': None,
                'min_disk': None,
                'min_ram': None,
                'disk_format': None,
                'container_format': None,
                'checksum': None,
                'created_at': self.NOW_DATETIME,
                'updated_at': self.NOW_DATETIME,
                'deleted': None,
                'owner': None,
                'visibility': None,
            }
            self.assertDictEqual(expected, meta)
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

    def test_update_with_data(self):
        fixture = self._make_fixture(name='test image')
        image = self.service.create(self.context, fixture)
        image_id = image['id']
        fixture['name'] = 'new image name'
        data = '*' * 256
        self.service.update(self.context, image_id, fixture, data=data)

        new_image_data = self.service.show(self.context, image_id)
        self.assertEqual(256, new_image_data['size'])
        self.assertEqual('new image name', new_image_data['name'])

    @mock.patch.object(glance.GlanceImageService, '_translate_from_glance')
    @mock.patch.object(glance.GlanceImageService, 'show')
    def test_update_purge_props(self, show, translate_from_glance):
        image_id = mock.sentinel.image_id
        client = mock.Mock(call=mock.Mock())
        service = glance.GlanceImageService(client=client)

        image_meta = {'properties': {'k1': 'v1'}}
        show.return_value = {'properties': {'k2': 'v2'}}
        translate_from_glance.return_value = image_meta.copy()

        ret = service.update(self.context, image_id, image_meta)
        self.assertDictEqual(image_meta, ret)
        client.call.assert_called_once_with(
            self.context, 'update', image_id, k1='v1', remove_props=['k2'])

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
            'protected': None,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted': None,
            'status': None,
            'properties': {'is_public': True, 'properties': {}},
            'owner': None,
            'visibility': None
        }
        self.assertEqual(expected, image_meta)

    def test_show_raises_when_no_authtoken_in_the_context(self):
        fixture = self._make_fixture(name='image1',
                                     is_public=False,
                                     protected=False)
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
                'protected': None,
                'size': None,
                'min_disk': None,
                'min_ram': None,
                'disk_format': None,
                'container_format': None,
                'checksum': None,
                'created_at': self.NOW_DATETIME,
                'updated_at': self.NOW_DATETIME,
                'deleted': None,
                'status': None,
                'properties': {'is_public': True, 'properties': {}},
                'owner': None,
                'visibility': None
            },
        ]
        self.assertEqual(expected, image_metas)

    def test_show_makes_datetimes(self):
        fixture = self._make_datetime_fixture()
        image_id = self.service.create(self.context, fixture)['id']
        image_meta = self.service.show(self.context, image_id)
        self.assertEqual(self.NOW_DATETIME, image_meta['created_at'])
        self.assertEqual(self.NOW_DATETIME, image_meta['updated_at'])

    def test_detail_makes_datetimes(self):
        fixture = self._make_datetime_fixture()
        self.service.create(self.context, fixture)
        image_meta = self.service.detail(self.context)[0]
        self.assertEqual(self.NOW_DATETIME, image_meta['created_at'])
        self.assertEqual(self.NOW_DATETIME, image_meta['updated_at'])

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

    def test_download_no_data(self):
        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            """Returns None instead of an iterator."""
            def data(self, image_id):
                return None

        client = MyGlanceStubClient()
        service = self._create_image_service(client)
        image_id = 'fake-image-uuid'
        e = self.assertRaises(exception.ImageDownloadFailed, service.download,
                              self.context, image_id)
        self.assertIn('image contains no data', six.text_type(e))
        self.assertIn(image_id, six.text_type(e))

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
    @mock.patch('cinder.image.glance.get_api_servers',
                return_value=itertools.cycle([(False, 'localhost:9292')]))
    def test_download_from_direct_file(self, api_servers,
                                       mock_copyfileobj, mock_open):
        fixture = self._make_fixture(name='test image',
                                     locations=[{'url': 'file:///tmp/test'}])
        image_id = self.service.create(self.context, fixture)['id']
        writer = NullWriter()
        self.flags(allowed_direct_url_schemes=['file'])
        self.service.download(self.context, image_id, writer)
        mock_copyfileobj.assert_called_once_with(mock.ANY, writer)

    @mock.patch('six.moves.builtins.open')
    @mock.patch('shutil.copyfileobj')
    @mock.patch('cinder.image.glance.get_api_servers',
                return_value=itertools.cycle([(False, 'localhost:9292')]))
    def test_download_from_direct_file_non_file(self, api_servers,
                                                mock_copyfileobj, mock_open):
        fixture = self._make_fixture(name='test image',
                                     direct_url='swift+http://test/image')
        image_id = self.service.create(self.context, fixture)['id']
        writer = NullWriter()
        self.flags(allowed_direct_url_schemes=['file'])
        self.service.download(self.context, image_id, writer)
        self.assertIsNone(mock_copyfileobj.call_args)

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
        self.assertEqual('something-less-likely', service._client.netloc)
        for ipv6_url in ('[::1]', '::1', '[::1]:444'):
            image_url = 'http://%s/%s' % (ipv6_url, image_id)
            (service, same_id) = glance.get_remote_image_service(self.context,
                                                                 image_url)
            self.assertEqual(same_id, image_id)
            self.assertEqual(ipv6_url, service._client.netloc)

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
                                    'min_disk', 'min_ram', 'is_public',
                                    'visibility', 'protected']
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
            'protected': None,
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
            'visibility': None,
            'cinder_encryption_key_id': None
        }
        self.assertEqual(expected, actual)

    @mock.patch('cinder.image.glance.CONF')
    def test_v2_passes_visibility_param(self, config):

        config.glance_num_retries = 0

        metadata = {
            'id': 1,
            'size': 2,
            'visibility': 'public',
        }

        image = glance_stubs.FakeImage(metadata)
        client = glance_stubs.StubGlanceClient()

        service = self._create_image_service(client)
        service._image_schema = glance_stubs.FakeSchema()

        actual = service._translate_from_glance('fake_context', image)
        expected = {
            'id': 1,
            'name': None,
            'visibility': 'public',
            'protected': None,
            'size': 2,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'deleted': None,
            'status': None,
            'properties': {},
            'owner': None,
            'created_at': None,
            'updated_at': None
        }

        self.assertEqual(expected, actual)

    @mock.patch('cinder.image.glance.CONF')
    def test_extracting_v2_boot_properties(self, config):

        config.glance_num_retries = 0

        metadata = {
            'id': 1,
            'size': 2,
            'min_disk': 2,
            'min_ram': 2,
            'kernel_id': 'foo',
            'ramdisk_id': 'bar',
        }

        image = glance_stubs.FakeImage(metadata)
        client = glance_stubs.StubGlanceClient()

        service = self._create_image_service(client)
        service._image_schema = glance_stubs.FakeSchema()

        actual = service._translate_from_glance('fake_context', image)
        expected = {
            'id': 1,
            'name': None,
            'visibility': None,
            'protected': None,
            'size': 2,
            'min_disk': 2,
            'min_ram': 2,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'deleted': None,
            'status': None,
            'properties': {'kernel_id': 'foo',
                           'ramdisk_id': 'bar'},
            'owner': None,
            'created_at': None,
            'updated_at': None
        }

        self.assertEqual(expected, actual)

    def test_translate_to_glance(self):
        client = glance_stubs.StubGlanceClient()
        service = self._create_image_service(client)

        metadata = {
            'id': 1,
            'size': 2,
            'min_disk': 2,
            'min_ram': 2,
            'properties': {'kernel_id': 'foo',
                           'ramdisk_id': 'bar',
                           'x_billinginfo': '123'},
        }

        actual = service._translate_to_glance(metadata)
        expected = {
            'id': 1,
            'size': 2,
            'min_disk': 2,
            'min_ram': 2,
            'kernel_id': 'foo',
            'ramdisk_id': 'bar',
            'x_billinginfo': '123',
        }
        self.assertEqual(expected, actual)

    @mock.patch('cinder.image.glance.glanceclient.Client')
    @mock.patch('cinder.image.glance.get_api_servers',
                return_value=itertools.cycle([(False, 'localhost:9292')]))
    def test_call_glance_over_quota(self, api_servers, _mockglanceclient):
        """Test glance version set by arg to GlanceClientWrapper"""
        glance_wrapper = glance.GlanceClientWrapper()
        fake_client = mock.Mock()
        fake_client.images.method = mock.Mock(
            side_effect=glanceclient.exc.HTTPOverLimit)
        self.mock_object(glance_wrapper, 'client', fake_client)
        self.assertRaises(exception.ImageLimitExceeded,
                          glance_wrapper.call, 'fake_context', 'method')


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
        self.mock_object(glance.time, 'sleep', return_value=None)
        service_auth.reset_globals()

    @mock.patch('cinder.service_auth.get_auth_plugin')
    @mock.patch.object(ks_session.Session, 'load_from_options')
    def test_create_glance_client_with_protocol_http(
            self, mock_load, mock_get_auth_plugin):
        glance._SESSION = None
        self.flags(auth_strategy='keystone')
        self.flags(glance_request_timeout=None)

        class MyGlanceStubClient(object):
            def __init__(inst, version, *args, **kwargs):
                self.assertEqual('2', version)
                self.assertEqual("http://fake_host:9292", args[0])
                self.assertNotIn('timeout', kwargs)
                self.assertIn("session", kwargs)
                self.assertIn("auth", kwargs)

        config_options = {'insecure': False,
                          'cacert': None,
                          'timeout': None,
                          'split_loggers': False}

        mock_get_auth_plugin.return_value = context._ContextAuthPlugin
        mock_load.return_value = session.Session
        self.mock_object(glance.glanceclient, 'Client', MyGlanceStubClient)
        client = glance._create_glance_client(self.context, 'fake_host:9292',
                                              False)
        self.assertIsInstance(client, MyGlanceStubClient)
        mock_get_auth_plugin.assert_called_once_with(self.context)
        mock_load.assert_called_once_with(**config_options)

    @mock.patch('cinder.service_auth.get_auth_plugin')
    @mock.patch.object(ks_session.Session, 'load_from_options')
    def test_create_glance_client_with_protocol_https(
            self, mock_load, mock_get_auth_plugin):
        glance._SESSION = None
        self.flags(auth_strategy='keystone')
        self.flags(glance_request_timeout=60)
        self.flags(
            glance_ca_certificates_file='/opt/stack/data/ca-bundle.pem')

        class MyGlanceStubClient(object):
            def __init__(inst, version, *args, **kwargs):
                self.assertEqual('2', version)
                self.assertEqual("https://fake_host:9292", args[0])
                self.assertNotIn('timeout', kwargs)
                self.assertIn("session", kwargs)
                self.assertIn("auth", kwargs)

        config_options = {'insecure': False,
                          'cacert': '/opt/stack/data/ca-bundle.pem',
                          'timeout': 60,
                          'split_loggers': False}

        mock_get_auth_plugin.return_value = context._ContextAuthPlugin
        mock_load.return_value = session.Session
        self.mock_object(glance.glanceclient, 'Client', MyGlanceStubClient)
        client = glance._create_glance_client(self.context, 'fake_host:9292',
                                              True)
        self.assertIsInstance(client, MyGlanceStubClient)
        mock_get_auth_plugin.assert_called_once_with(self.context)
        mock_load.assert_called_once_with(**config_options)

    def test_create_glance_client_auth_strategy_noauth_with_protocol_https(
            self):
        self.flags(auth_strategy='noauth')
        self.flags(glance_request_timeout=60)
        self.flags(glance_api_insecure=False)
        self.flags(
            glance_ca_certificates_file='/opt/stack/data/ca-bundle.pem')

        class MyGlanceStubClient(object):
            def __init__(inst, version, *args, **kwargs):
                self.assertEqual('2', version)
                self.assertEqual('https://fake_host:9292', args[0])
                self.assertEqual(60, kwargs['timeout'])
                self.assertNotIn("session", kwargs)
                self.assertNotIn("auth", kwargs)
                self.assertEqual(
                    '/opt/stack/data/ca-bundle.pem', kwargs['cacert'])
                self.assertEqual(False, kwargs['insecure'])

        self.mock_object(glance.glanceclient, 'Client', MyGlanceStubClient)
        client = glance._create_glance_client(self.context, 'fake_host:9292',
                                              True)
        self.assertIsInstance(client, MyGlanceStubClient)

    def test_create_glance_client_auth_strategy_noauth_with_protocol_http(
            self):
        self.flags(auth_strategy='noauth')
        self.flags(glance_request_timeout=None)

        class MyGlanceStubClient(object):
            def __init__(inst, version, *args, **kwargs):
                self.assertEqual('2', version)
                self.assertEqual("http://fake_host:9292", args[0])
                self.assertNotIn('timeout', kwargs)
                self.assertNotIn("session", kwargs)
                self.assertNotIn("auth", kwargs)

        self.mock_object(glance.glanceclient, 'Client', MyGlanceStubClient)
        client = glance._create_glance_client(self.context, 'fake_host:9292',
                                              False)
        self.assertIsInstance(client, MyGlanceStubClient)
