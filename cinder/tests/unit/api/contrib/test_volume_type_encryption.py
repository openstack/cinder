# Copyright (c) 2013 The Johns Hopkins University/Applied Physics Laboratory
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

import json
import mock

import webob

from cinder.api.openstack import wsgi
from cinder import context
from cinder import db
from cinder import test
from cinder.tests.unit.api import fakes


def return_volume_type_encryption(context, volume_type_id):
    return stub_volume_type_encryption()


def stub_volume_type_encryption():
    values = {
        'cipher': 'fake_cipher',
        'control_location': 'front-end',
        'key_size': 256,
        'provider': 'fake_provider',
        'volume_type_id': 'fake_type_id',
    }
    return values


class VolumeTypeEncryptionTest(test.TestCase):

    _default_volume_type = {
        'id': 'fake_type_id',
        'name': 'fake_type',
    }

    def setUp(self):
        super(VolumeTypeEncryptionTest, self).setUp()
        self.flags(host='fake')
        self.api_path = '/v2/fake/os-volume-types/1/encryption'
        """to reset notifier drivers left over from other api/contrib tests"""

    def _get_response(self, volume_type, admin=True,
                      url='/v2/fake/types/%s/encryption',
                      req_method='GET', req_body=None,
                      req_headers=None):
        ctxt = context.RequestContext('fake', 'fake', is_admin=admin)

        req = webob.Request.blank(url % volume_type['id'])
        req.method = req_method
        req.body = req_body
        if req_headers:
            req.headers['Content-Type'] = req_headers

        return req.get_response(fakes.wsgi_app(fake_auth_context=ctxt))

    def _create_type_and_encryption(self, volume_type, body=None):
        if body is None:
            body = {"encryption": stub_volume_type_encryption()}

        db.volume_type_create(context.get_admin_context(), volume_type)

        return self._get_response(volume_type, req_method='POST',
                                  req_body=json.dumps(body),
                                  req_headers='application/json')

    def test_index(self):
        self.stubs.Set(db, 'volume_type_encryption_get',
                       return_volume_type_encryption)

        volume_type = self._default_volume_type
        self._create_type_and_encryption(volume_type)

        res = self._get_response(volume_type)
        self.assertEqual(200, res.status_code)
        res_dict = json.loads(res.body)

        expected = stub_volume_type_encryption()
        self.assertEqual(expected, res_dict)

        db.volume_type_destroy(context.get_admin_context(), volume_type['id'])

    def test_index_invalid_type(self):
        volume_type = self._default_volume_type
        res = self._get_response(volume_type)
        self.assertEqual(404, res.status_code)
        res_dict = json.loads(res.body)

        expected = {
            'itemNotFound': {
                'code': 404,
                'message': ('Volume type %s could not be found.'
                            % volume_type['id'])
            }
        }
        self.assertEqual(expected, res_dict)

    def test_show_key_size(self):
        volume_type = self._default_volume_type
        self._create_type_and_encryption(volume_type)
        res = self._get_response(volume_type,
                                 url='/v2/fake/types/%s/encryption/key_size')
        res_dict = json.loads(res.body)

        self.assertEqual(200, res.status_code)
        self.assertEqual(256, res_dict['key_size'])

        db.volume_type_destroy(context.get_admin_context(), volume_type['id'])

    def test_show_provider(self):
        volume_type = self._default_volume_type
        self._create_type_and_encryption(volume_type)

        res = self._get_response(volume_type,
                                 url='/v2/fake/types/%s/encryption/provider')
        res_dict = json.loads(res.body)

        self.assertEqual(200, res.status_code)
        self.assertEqual('fake_provider', res_dict['provider'])
        db.volume_type_destroy(context.get_admin_context(), volume_type['id'])

    def test_show_item_not_found(self):
        volume_type = self._default_volume_type
        self._create_type_and_encryption(volume_type)

        res = self._get_response(volume_type,
                                 url='/v2/fake/types/%s/encryption/fake')
        res_dict = json.loads(res.body)

        self.assertEqual(404, res.status_code)
        expected = {
            'itemNotFound': {
                'code': 404,
                'message': ('The resource could not be found.')
            }
        }
        self.assertEqual(expected, res_dict)
        db.volume_type_destroy(context.get_admin_context(), volume_type['id'])

    def _create(self, cipher, control_location, key_size, provider):
        volume_type = self._default_volume_type
        db.volume_type_create(context.get_admin_context(), volume_type)

        body = {"encryption": {'cipher': cipher,
                               'control_location': control_location,
                               'key_size': key_size,
                               'provider': provider,
                               'volume_type_id': volume_type['id']}}

        self.assertEqual(0, len(self.notifier.notifications))
        res = self._get_response(volume_type)
        res_dict = json.loads(res.body)
        self.assertEqual(200, res.status_code)
        # Confirm that volume type has no encryption information
        # before create.
        self.assertEqual('{}', res.body)

        # Create encryption specs for the volume type
        # with the defined body.
        res = self._get_response(volume_type, req_method='POST',
                                 req_body=json.dumps(body),
                                 req_headers='application/json')
        res_dict = json.loads(res.body)

        self.assertEqual(1, len(self.notifier.notifications))

        # check response
        self.assertIn('encryption', res_dict)
        self.assertEqual(cipher, res_dict['encryption']['cipher'])
        self.assertEqual(control_location,
                         res_dict['encryption']['control_location'])
        self.assertEqual(key_size, res_dict['encryption']['key_size'])
        self.assertEqual(provider, res_dict['encryption']['provider'])
        self.assertEqual(volume_type['id'],
                         res_dict['encryption']['volume_type_id'])

        # check database
        encryption = db.volume_type_encryption_get(context.get_admin_context(),
                                                   volume_type['id'])
        self.assertIsNotNone(encryption)
        self.assertEqual(cipher, encryption['cipher'])
        self.assertEqual(key_size, encryption['key_size'])
        self.assertEqual(provider, encryption['provider'])
        self.assertEqual(volume_type['id'], encryption['volume_type_id'])

        db.volume_type_destroy(context.get_admin_context(), volume_type['id'])

    def test_create_json(self):
        with mock.patch.object(wsgi.Controller,
                               'validate_integer') as mock_validate_integer:
            mock_validate_integer.return_value = 128
            self._create('fake_cipher', 'front-end', 128, 'fake_encryptor')
            self.assertTrue(mock_validate_integer.called)

    def test_create_xml(self):
        volume_type = self._default_volume_type
        db.volume_type_create(context.get_admin_context(), volume_type)

        ctxt = context.RequestContext('fake', 'fake', is_admin=True)

        req = webob.Request.blank('/v2/fake/types/%s/encryption'
                                  % volume_type['id'])
        req.method = 'POST'
        req.body = ('<encryption provider="test_provider" '
                    'cipher="cipher" control_location="front-end" />')
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctxt))

        self.assertEqual(200, res.status_int)

        db.volume_type_destroy(context.get_admin_context(), volume_type['id'])

    def test_create_invalid_volume_type(self):
        volume_type = self._default_volume_type
        body = {"encryption": stub_volume_type_encryption()}

        # Attempt to create encryption without first creating type
        res = self._get_response(volume_type, req_method='POST',
                                 req_body=json.dumps(body),
                                 req_headers='application/json')
        res_dict = json.loads(res.body)

        self.assertEqual(0, len(self.notifier.notifications))
        self.assertEqual(404, res.status_code)

        expected = {
            'itemNotFound': {
                'code': 404,
                'message': ('Volume type %s could not be found.'
                            % volume_type['id'])
            }
        }
        self.assertEqual(expected, res_dict)

    def test_create_encryption_type_exists(self):
        volume_type = self._default_volume_type
        body = {"encryption": stub_volume_type_encryption()}
        self._create_type_and_encryption(volume_type, body)

        # Try to create encryption specs for a volume type
        # that already has them.
        res = self._get_response(volume_type, req_method='POST',
                                 req_body=json.dumps(body),
                                 req_headers='application/json')
        res_dict = json.loads(res.body)

        expected = {
            'badRequest': {
                'code': 400,
                'message': ('Volume type encryption for type '
                            'fake_type_id already exists.')
            }
        }
        self.assertEqual(expected, res_dict)
        db.volume_type_destroy(context.get_admin_context(), volume_type['id'])

    def test_create_volume_exists(self):
        # Create the volume type and a volume with the volume type.
        volume_type = self._default_volume_type
        db.volume_type_create(context.get_admin_context(), volume_type)
        db.volume_create(context.get_admin_context(),
                         {'id': 'fake_id',
                          'display_description': 'Test Desc',
                          'size': 20,
                          'status': 'creating',
                          'instance_uuid': None,
                          'host': 'dummy',
                          'volume_type_id': volume_type['id']})

        body = {"encryption": {'cipher': 'cipher',
                               'key_size': 128,
                               'control_location': 'front-end',
                               'provider': 'fake_provider',
                               'volume_type_id': volume_type['id']}}

        # Try to create encryption specs for a volume type
        # with a volume.
        res = self._get_response(volume_type, req_method='POST',
                                 req_body=json.dumps(body),
                                 req_headers='application/json')
        res_dict = json.loads(res.body)

        expected = {
            'badRequest': {
                'code': 400,
                'message': ('Cannot create encryption specs. '
                            'Volume type in use.')
            }
        }
        self.assertEqual(expected, res_dict)
        db.volume_destroy(context.get_admin_context(), 'fake_id')
        db.volume_type_destroy(context.get_admin_context(), volume_type['id'])

    def _encryption_create_bad_body(self, body,
                                    msg='Create body is not valid.'):

        volume_type = self._default_volume_type
        db.volume_type_create(context.get_admin_context(), volume_type)
        res = self._get_response(volume_type, req_method='POST',
                                 req_body=json.dumps(body),
                                 req_headers='application/json')

        res_dict = json.loads(res.body)

        expected = {
            'badRequest': {
                'code': 400,
                'message': (msg)
            }
        }
        self.assertEqual(expected, res_dict)
        db.volume_type_destroy(context.get_admin_context(), volume_type['id'])

    def test_create_no_body(self):
        msg = "Missing required element 'encryption' in request body."
        self._encryption_create_bad_body(body=None, msg=msg)

    def test_create_malformed_entity(self):
        body = {'encryption': 'string'}
        msg = "Missing required element 'encryption' in request body."
        self._encryption_create_bad_body(body=body, msg=msg)

    def test_create_negative_key_size(self):
        body = {"encryption": {'cipher': 'cipher',
                               'key_size': -128,
                               'provider': 'fake_provider',
                               'volume_type_id': 'volume_type'}}
        msg = 'key_size must be >= 0'
        self._encryption_create_bad_body(body=body, msg=msg)

    def test_create_none_key_size(self):
        self._create('fake_cipher', 'front-end', None, 'fake_encryptor')

    def test_create_invalid_control_location(self):
        body = {"encryption": {'cipher': 'cipher',
                               'control_location': 'fake_control',
                               'provider': 'fake_provider',
                               'volume_type_id': 'volume_type'}}
        msg = ("Invalid input received: Valid control location are: "
               "['front-end', 'back-end']")
        self._encryption_create_bad_body(body=body, msg=msg)

    def test_create_no_provider(self):
        body = {"encryption": {'cipher': 'cipher',
                               'volume_type_id': 'volume_type'}}
        msg = ("Invalid input received: provider must be defined")
        self._encryption_create_bad_body(body=body, msg=msg)

    def test_delete(self):
        volume_type = self._default_volume_type
        db.volume_type_create(context.get_admin_context(), volume_type)

        # Test that before create, there's nothing with a get
        res = self._get_response(volume_type)
        self.assertEqual(200, res.status_code)
        res_dict = json.loads(res.body)
        self.assertEqual({}, res_dict)

        body = {"encryption": {'cipher': 'cipher',
                               'key_size': 128,
                               'control_location': 'front-end',
                               'provider': 'fake_provider',
                               'volume_type_id': volume_type['id']}}

        # Create, and test that get returns something
        res = self._get_response(volume_type, req_method='POST',
                                 req_body=json.dumps(body),
                                 req_headers='application/json')
        res_dict = json.loads(res.body)

        res = self._get_response(volume_type, req_method='GET',
                                 req_headers='application/json',
                                 url='/v2/fake/types/%s/encryption')
        self.assertEqual(200, res.status_code)
        res_dict = json.loads(res.body)
        self.assertEqual(volume_type['id'], res_dict['volume_type_id'])

        # Delete, and test that get returns nothing
        res = self._get_response(volume_type, req_method='DELETE',
                                 req_headers='application/json',
                                 url='/v2/fake/types/%s/encryption/provider')
        self.assertEqual(202, res.status_code)
        self.assertEqual(0, len(res.body))
        res = self._get_response(volume_type, req_method='GET',
                                 req_headers='application/json',
                                 url='/v2/fake/types/%s/encryption')
        self.assertEqual(200, res.status_code)
        res_dict = json.loads(res.body)
        self.assertEqual({}, res_dict)

        db.volume_type_destroy(context.get_admin_context(), volume_type['id'])

    def test_delete_with_volume_in_use(self):
        # Create the volume type
        volume_type = self._default_volume_type
        db.volume_type_create(context.get_admin_context(), volume_type)

        body = {"encryption": {'cipher': 'cipher',
                               'key_size': 128,
                               'control_location': 'front-end',
                               'provider': 'fake_provider',
                               'volume_type_id': volume_type['id']}}

        # Create encryption with volume type, and test with GET
        res = self._get_response(volume_type, req_method='POST',
                                 req_body=json.dumps(body),
                                 req_headers='application/json')
        res = self._get_response(volume_type, req_method='GET',
                                 req_headers='application/json',
                                 url='/v2/fake/types/%s/encryption')
        self.assertEqual(200, res.status_code)
        res_dict = json.loads(res.body)
        self.assertEqual(volume_type['id'], res_dict['volume_type_id'])

        # Create volumes with the volume type
        db.volume_create(context.get_admin_context(),
                         {'id': 'fake_id',
                          'display_description': 'Test Desc',
                          'size': 20,
                          'status': 'creating',
                          'instance_uuid': None,
                          'host': 'dummy',
                          'volume_type_id': volume_type['id']})

        db.volume_create(context.get_admin_context(),
                         {'id': 'fake_id2',
                          'display_description': 'Test Desc2',
                          'size': 2,
                          'status': 'creating',
                          'instance_uuid': None,
                          'host': 'dummy',
                          'volume_type_id': volume_type['id']})

        # Delete, and test that there is an error since volumes exist
        res = self._get_response(volume_type, req_method='DELETE',
                                 req_headers='application/json',
                                 url='/v2/fake/types/%s/encryption/provider')
        self.assertEqual(400, res.status_code)
        res_dict = json.loads(res.body)
        expected = {
            'badRequest': {
                'code': 400,
                'message': 'Cannot delete encryption specs. '
                           'Volume type in use.'
            }
        }
        self.assertEqual(expected, res_dict)

        # Delete the volumes
        db.volume_destroy(context.get_admin_context(), 'fake_id')
        db.volume_destroy(context.get_admin_context(), 'fake_id2')

        # Delete, and test that get returns nothing
        res = self._get_response(volume_type, req_method='DELETE',
                                 req_headers='application/json',
                                 url='/v2/fake/types/%s/encryption/provider')
        self.assertEqual(202, res.status_code)
        self.assertEqual(0, len(res.body))
        res = self._get_response(volume_type, req_method='GET',
                                 req_headers='application/json',
                                 url='/v2/fake/types/%s/encryption')
        self.assertEqual(200, res.status_code)
        res_dict = json.loads(res.body)
        self.assertEqual({}, res_dict)

        db.volume_type_destroy(context.get_admin_context(), volume_type['id'])

    def test_delete_with_no_encryption(self):
        volume_type = self._default_volume_type
        # create an volume type
        db.volume_type_create(context.get_admin_context(), volume_type)

        # without creating encryption type, try to delete
        # and check if 404 is raised.
        res = self._get_response(volume_type, req_method='DELETE',
                                 req_headers='application/json',
                                 url='/v2/fake/types/%s/encryption/provider')
        self.assertEqual(404, res.status_code)
        expected = {
            "itemNotFound": {
                "message": "Volume type encryption for type "
                           "fake_type_id does not exist.",
                "code": 404
            }
        }
        self.assertEqual(expected, json.loads(res.body))
        db.volume_type_destroy(context.get_admin_context(), volume_type['id'])

    @mock.patch('cinder.api.openstack.wsgi.Controller.validate_integer')
    def test_update_item(self, mock_validate_integer):
        mock_validate_integer.return_value = 512
        volume_type = self._default_volume_type

        # Create Encryption Specs
        create_body = {"encryption": {'cipher': 'cipher',
                                      'control_location': 'front-end',
                                      'key_size': 128,
                                      'provider': 'fake_provider',
                                      'volume_type_id': volume_type['id']}}
        self._create_type_and_encryption(volume_type, create_body)

        # Update Encryption Specs
        update_body = {"encryption": {'key_size': 512,
                                      'provider': 'fake_provider2'}}

        res = self.\
            _get_response(volume_type, req_method='PUT',
                          req_body=json.dumps(update_body),
                          req_headers='application/json',
                          url='/v2/fake/types/%s/encryption/fake_type_id')

        res_dict = json.loads(res.body)
        self.assertEqual(512, res_dict['encryption']['key_size'])
        self.assertEqual('fake_provider2', res_dict['encryption']['provider'])

        # Get Encryption Specs
        res = self._get_response(volume_type)
        res_dict = json.loads(res.body)

        # Confirm Encryption Specs
        self.assertEqual(512, res_dict['key_size'])
        self.assertEqual('fake_provider2', res_dict['provider'])
        self.assertTrue(mock_validate_integer.called)

        db.volume_type_destroy(context.get_admin_context(), volume_type['id'])

    def _encryption_update_bad_body(self, update_body, msg):

        # Create Volume Type and Encryption
        volume_type = self._default_volume_type
        res = self._create_type_and_encryption(volume_type)

        # Update Encryption
        res = self.\
            _get_response(volume_type, req_method='PUT',
                          req_body=json.dumps(update_body),
                          req_headers='application/json',
                          url='/v2/fake/types/%s/encryption/fake_type_id')

        res_dict = json.loads(res.body)

        expected = {
            'badRequest': {
                'code': 400,
                'message': (msg)
            }
        }

        # Confirm Failure
        self.assertEqual(expected, res_dict)
        db.volume_type_destroy(context.get_admin_context(), volume_type['id'])

    def test_update_too_many_items(self):
        update_body = {"encryption": {'key_size': 512},
                       "encryption2": {'key_size': 256}}
        msg = 'Request body contains too many items.'
        self._encryption_update_bad_body(update_body, msg)

    def test_update_key_size_non_integer(self):
        update_body = {"encryption": {'key_size': 'abc'}}
        msg = 'key_size must be an integer.'
        self._encryption_update_bad_body(update_body, msg)

    def test_update_item_invalid_body(self):
        update_body = {"key_size": "value1"}
        msg = "Missing required element 'encryption' in request body."
        self._encryption_update_bad_body(update_body, msg)

    def _encryption_empty_update(self, update_body):
        msg = "Missing required element 'encryption' in request body."
        self._encryption_update_bad_body(update_body, msg)

    def test_update_no_body(self):
        self._encryption_empty_update(update_body=None)

    def test_update_empty_body(self):
        self._encryption_empty_update(update_body={})

    def test_update_with_volume_in_use(self):
        # Create the volume type and encryption
        volume_type = self._default_volume_type
        self._create_type_and_encryption(volume_type)

        # Create a volume with the volume type
        db.volume_create(context.get_admin_context(),
                         {'id': 'fake_id',
                          'display_description': 'Test Desc',
                          'size': 20,
                          'status': 'creating',
                          'instance_uuid': None,
                          'host': 'dummy',
                          'volume_type_id': volume_type['id']})

        # Get the Encryption
        res = self._get_response(volume_type)
        self.assertEqual(200, res.status_code)
        res_dict = json.loads(res.body)
        self.assertEqual(volume_type['id'], res_dict['volume_type_id'])

        # Update, and test that there is an error since volumes exist
        update_body = {"encryption": {'key_size': 512}}

        res = self.\
            _get_response(volume_type, req_method='PUT',
                          req_body=json.dumps(update_body),
                          req_headers='application/json',
                          url='/v2/fake/types/%s/encryption/fake_type_id')
        self.assertEqual(400, res.status_code)
        res_dict = json.loads(res.body)
        expected = {
            'badRequest': {
                'code': 400,
                'message': 'Cannot update encryption specs. '
                           'Volume type in use.'
            }
        }
        self.assertEqual(expected, res_dict)
