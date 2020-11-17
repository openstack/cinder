# Copyright (c) 2016 Synology Inc. All rights reserved.
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


import base64
import functools
import json
import math
from os import urandom
from random import randint
import re

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers import modes
import eventlet
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils.secretutils import md5
from oslo_utils import units
import requests
from six.moves import urllib
from six import string_types

from cinder import exception
from cinder.i18n import _
from cinder.objects import snapshot
from cinder.objects import volume
from cinder import utils
from cinder.volume import configuration
from cinder.volume import volume_utils


cinder_opts = [
    cfg.StrOpt('synology_pool_name',
               default='',
               help='Volume on Synology storage to be used for creating lun.'),
    cfg.PortOpt('synology_admin_port',
                default=5000,
                help='Management port for Synology storage.'),
    cfg.StrOpt('synology_username',
               default='admin',
               help='Administrator of Synology storage.'),
    cfg.StrOpt('synology_password',
               default='',
               help='Password of administrator for logging in '
                    'Synology storage.',
               secret=True),
    cfg.BoolOpt('synology_ssl_verify',
                default=True,
                help='Do certificate validation or not if '
                     '$driver_use_ssl is True'),
    cfg.StrOpt('synology_one_time_pass',
               default=None,
               help='One time password of administrator for logging in '
                    'Synology storage if OTP is enabled.',
               secret=True),
    cfg.StrOpt('synology_device_id',
               default=None,
               help='Device id for skip one time password check for '
                    'logging in Synology storage if OTP is enabled.'),
]

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.register_opts(cinder_opts, group=configuration.SHARED_CONF_GROUP)


class SynoAPIHTTPError(exception.VolumeDriverException):
    message = _("HTTP exit code: [%(code)s]")


class SynoAuthError(exception.VolumeDriverException):
    message = _("Synology driver authentication failed: %(reason)s.")


class SynoLUNNotExist(exception.VolumeDriverException):
    message = _("LUN not found by UUID: %(uuid)s.")


class AESCipher(object):
    """Encrypt with OpenSSL-compatible way"""

    SALT_MAGIC = b'Salted__'

    def __init__(self, password, key_length=32):
        self._bs = 16
        self._salt = urandom(self._bs - len(self.SALT_MAGIC))

        self._key, self._iv = self._derive_key_and_iv(password,
                                                      self._salt,
                                                      key_length,
                                                      self._bs)

    def _pad(self, s):
        bs = self._bs
        return (s + (bs - len(s) % bs) * chr(bs - len(s) % bs)).encode('utf-8')

    # TODO(alee): This probably needs to be replaced with a version that
    # does not use md5, as this will be disallowed on a FIPS enabled system
    def _derive_key_and_iv(self, password, salt, key_length, iv_length):
        d = d_i = b''
        while len(d) < key_length + iv_length:
            md5_str = d_i + password + salt
            d_i = md5(md5_str, usedforsecurity=True).digest()
            d += d_i
        return d[:key_length], d[key_length:key_length + iv_length]

    def encrypt(self, text):
        cipher = Cipher(
            algorithms.AES(self._key),
            modes.CBC(self._iv),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(self._pad(text)) + encryptor.finalize()

        return self.SALT_MAGIC + self._salt + ciphertext


class Session(object):
    def __init__(self,
                 host,
                 port,
                 username,
                 password,
                 https=False,
                 ssl_verify=True,
                 one_time_pass=None,
                 device_id=None):
        self._proto = 'https' if https else 'http'
        self._host = host
        self._port = port
        self._sess = 'dsm'
        self._https = https
        self._url_prefix = self._proto + '://' + host + ':' + str(port)
        self._url = self._url_prefix + '/webapi/auth.cgi'
        self._ssl_verify = ssl_verify
        self._sid = None
        self._did = device_id

        data = {'api': 'SYNO.API.Auth',
                'method': 'login',
                'version': 6}

        params = {'account': username,
                  'passwd': password,
                  'session': self._sess,
                  'format': 'sid'}

        if one_time_pass:
            if device_id:
                params.update(device_id=device_id)
            else:
                params.update(otp_code=one_time_pass,
                              enable_device_token='yes')

        if not https:
            params = self._encrypt_params(params)

        data.update(params)

        resp = requests.post(self._url,
                             data=data,
                             verify=self._ssl_verify)
        result = resp.json()

        if result and result['success']:
            self._sid = result['data']['sid']
            if one_time_pass and not device_id:
                self._did = result['data']['did']
        else:
            raise SynoAuthError(reason=_('Login failed.'))

    def _random_AES_passphrase(self, length):
        available = ('0123456789'
                     'abcdefghijklmnopqrstuvwxyz'
                     'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                     '~!@#$%^&*()_+-/')
        key = b''

        while length > 0:
            key += available[randint(0, len(available) - 1)].encode('utf-8')
            length -= 1

        return key

    def _get_enc_info(self):
        url = self.url_prefix() + '/webapi/encryption.cgi'
        data = {"api": "SYNO.API.Encryption",
                "method": "getinfo",
                "version": 1,
                "format": "module"}

        resp = requests.post(url, data=data, verify=self._ssl_verify)
        result = resp.json()

        return result["data"]

    def _encrypt_RSA(self, modulus, passphrase, text):
        public_numbers = rsa.RSAPublicNumbers(passphrase, modulus)
        public_key = public_numbers.public_key(default_backend())

        if isinstance(text, str):
            text = text.encode('utf-8')

        ciphertext = public_key.encrypt(
            text,
            padding.PKCS1v15()
        )
        return ciphertext

    def _encrypt_AES(self, passphrase, text):
        cipher = AESCipher(passphrase)

        return cipher.encrypt(text)

    def _encrypt_params(self, params):
        enc_info = self._get_enc_info()
        public_key = enc_info["public_key"]
        cipher_key = enc_info["cipherkey"]
        cipher_token = enc_info["ciphertoken"]
        server_time = enc_info["server_time"]
        random_passphrase = self._random_AES_passphrase(501)

        params[cipher_token] = server_time

        encrypted_passphrase = self._encrypt_RSA(int(public_key, 16),
                                                 int("10001", 16),
                                                 random_passphrase)

        encrypted_params = self._encrypt_AES(random_passphrase,
                                             urllib.parse.urlencode(params))

        enc_params = {
            "rsa": base64.b64encode(encrypted_passphrase).decode("ascii"),
            "aes": base64.b64encode(encrypted_params).decode("ascii")
        }

        return {cipher_key: json.dumps(enc_params)}

    def sid(self):
        return self._sid

    def did(self):
        return self._did

    def url_prefix(self):
        return self._url_prefix

    def query(self, api):
        url = self._url_prefix + '/webapi/query.cgi'
        data = {'api': 'SYNO.API.Info',
                'version': 1,
                'method': 'query',
                'query': api}

        resp = requests.post(url,
                             data=data,
                             verify=self._ssl_verify)
        result = resp.json()

        if 'success' in result and result['success']:
            return result['data'][api]
        else:
            return None

    def __del__(self):
        if not hasattr(self, '_sid'):
            return

        data = {'api': 'SYNO.API.Auth',
                'version': 1,
                'method': 'logout',
                'session': self._sess,
                '_sid': self._sid}

        requests.post(self._url, data=data, verify=self._ssl_verify)


def _connection_checker(func):
    """Decorator to check session has expired or not."""
    @functools.wraps(func)
    def inner_connection_checker(self, *args, **kwargs):
        LOG.debug('in _connection_checker')
        for attempts in range(2):
            try:
                return func(self, *args, **kwargs)
            except SynoAuthError as e:
                if attempts < 1:
                    LOG.debug('Session might have expired.'
                              ' Trying to relogin')
                    self.new_session()
                    continue
                else:
                    LOG.error('Try to renew session: [%s]', e)
                    raise
    return inner_connection_checker


class APIRequest(object):
    def __init__(self,
                 host,
                 port,
                 username,
                 password,
                 https=False,
                 ssl_verify=True,
                 one_time_pass=None,
                 device_id=None):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._https = https
        self._ssl_verify = ssl_verify
        self._one_time_pass = one_time_pass
        self._device_id = device_id

        self.new_session()

    def new_session(self):
        self.__session = Session(self._host,
                                 self._port,
                                 self._username,
                                 self._password,
                                 self._https,
                                 self._ssl_verify,
                                 self._one_time_pass,
                                 self._device_id)
        if not self._device_id:
            self._device_id = self.__session.did()

    def _start(self, api, version):
        apiInfo = self.__session.query(api)
        self._jsonFormat = apiInfo['requestFormat'] == 'JSON'
        if (apiInfo and (apiInfo['minVersion'] <= version)
                and (apiInfo['maxVersion'] >= version)):
            return apiInfo['path']
        else:
            raise exception.APIException(service=api)

    def _encode_param(self, params):
        # Json encode
        if self._jsonFormat:
            for key, value in params.items():
                params[key] = json.dumps(value)
        # url encode
        return urllib.parse.urlencode(params)

    @utils.synchronized('Synology')
    @_connection_checker
    def request(self, api, method, version, **params):
        cgi_path = self._start(api, version)
        s = self.__session
        url = s.url_prefix() + '/webapi/' + cgi_path
        data = {'api': api,
                'version': version,
                'method': method,
                '_sid': s.sid()
                }

        data.update(params)

        LOG.debug('[%s]', url)
        LOG.debug('%s', json.dumps(data, indent=4))

        # Send HTTP Post Request
        resp = requests.post(url,
                             data=self._encode_param(data),
                             verify=self._ssl_verify)

        http_status = resp.status_code
        result = resp.json()

        LOG.debug('%s', json.dumps(result, indent=4))

        # Check for status code
        if (200 != http_status):
            result = {'http_status': http_status}
        elif 'success' not in result:
            reason = _("'success' not found")
            raise exception.MalformedResponse(cmd=json.dumps(data, indent=4),
                                              reason=reason)

        if ('error' in result and 'code' in result["error"]
                and result['error']['code'] in [105, 119]):
            raise SynoAuthError(reason=_('Session might have expired.'))

        return result


class SynoCommon(object):
    """Manage Cinder volumes on Synology storage"""

    TARGET_NAME_PREFIX = 'Cinder-Target-'
    CINDER_LUN = 'CINDER'
    METADATA_DS_SNAPSHOT_UUID = 'ds_snapshot_UUID'

    def __init__(self, config, driver_type):
        if not config.safe_get('target_ip_address'):
            raise exception.InvalidConfigurationValue(
                option='target_ip_address',
                value='')
        if not config.safe_get('synology_pool_name'):
            raise exception.InvalidConfigurationValue(
                option='synology_pool_name',
                value='')

        self.config = config
        self.vendor_name = 'Synology'
        self.driver_type = driver_type
        self.volume_backend_name = self._get_backend_name()
        self.target_port = self.config.safe_get('target_port')

        api = APIRequest(self.config.target_ip_address,
                         self.config.synology_admin_port,
                         self.config.synology_username,
                         self.config.synology_password,
                         self.config.safe_get('driver_use_ssl'),
                         self.config.safe_get('synology_ssl_verify'),
                         self.config.safe_get('synology_one_time_pass'),
                         self.config.safe_get('synology_device_id'),)
        self.synoexec = api.request
        self.host_uuid = self._get_node_uuid()

    def _get_node_uuid(self):
        try:
            out = self.exec_webapi('SYNO.Core.ISCSI.Node',
                                   'list',
                                   1)

            self.check_response(out)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to _get_node_uuid.')

        if (not self.check_value_valid(out, ['data', 'nodes'], list)
                or 0 >= len(out['data']['nodes'])
                or not self.check_value_valid(out['data']['nodes'][0],
                                              ['uuid'],
                                              string_types)):
            msg = _('Failed to _get_node_uuid.')
            raise exception.VolumeDriverException(message=msg)

        return out['data']['nodes'][0]['uuid']

    def _get_pool_info(self):
        pool_name = self.config.synology_pool_name
        if not pool_name:
            raise exception.InvalidConfigurationValue(option='pool_name',
                                                      value='')
        try:
            out = self.exec_webapi('SYNO.Core.Storage.Volume',
                                   'get',
                                   1,
                                   volume_path='/' + pool_name)

            self.check_response(out)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to _get_pool_status.')

        if not self.check_value_valid(out, ['data', 'volume'], object):
            raise exception.MalformedResponse(cmd='_get_pool_info',
                                              reason=_('no data found'))

        return out['data']['volume']

    def _get_pool_size(self):
        info = self._get_pool_info()

        if 'size_free_byte' not in info or 'size_total_byte' not in info:
            raise exception.MalformedResponse(cmd='_get_pool_size',
                                              reason=_('size not found'))

        free_capacity_gb = int(int(info['size_free_byte']) / units.Gi)
        total_capacity_gb = int(int(info['size_total_byte']) / units.Gi)
        other_user_data_gb = int(math.ceil((float(info['size_total_byte']) -
                                            float(info['size_free_byte']) -
                                            float(info['eppool_used_byte'])) /
                                 units.Gi))

        return free_capacity_gb, total_capacity_gb, other_user_data_gb

    def _get_pool_lun_provisioned_size(self):
        pool_name = self.config.synology_pool_name
        if not pool_name:
            raise exception.InvalidConfigurationValue(option='pool_name',
                                                      value=pool_name)
        try:
            out = self.exec_webapi('SYNO.Core.ISCSI.LUN',
                                   'list',
                                   1,
                                   location='/' + pool_name)

            self.check_response(out)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to _get_pool_lun_provisioned_size.')

        if not self.check_value_valid(out, ['data', 'luns'], list):
            raise exception.MalformedResponse(
                cmd='_get_pool_lun_provisioned_size',
                reason=_('no data found'))

        size = 0
        for lun in out['data']['luns']:
            size += lun['size']

        return int(math.ceil(float(size) / units.Gi))

    def _get_lun_info(self, lun_name, additional=None):
        if not lun_name:
            err = _('Param [lun_name] is invalid.')
            raise exception.InvalidParameterValue(err=err)

        params = {'uuid': lun_name}
        if additional is not None:
            params['additional'] = additional

        try:
            out = self.exec_webapi('SYNO.Core.ISCSI.LUN',
                                   'get',
                                   1,
                                   **params)

            self.check_response(out, uuid=lun_name)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to _get_lun_info. [%s]', lun_name)

        if not self.check_value_valid(out, ['data', 'lun'], object):
            raise exception.MalformedResponse(cmd='_get_lun_info',
                                              reason=_('lun info not found'))

        return out['data']['lun']

    def _get_lun_uuid(self, lun_name):
        if not lun_name:
            err = _('Param [lun_name] is invalid.')
            raise exception.InvalidParameterValue(err=err)

        try:
            lun_info = self._get_lun_info(lun_name)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to _get_lun_uuid. [%s]', lun_name)

        if not self.check_value_valid(lun_info, ['uuid'], string_types):
            raise exception.MalformedResponse(cmd='_get_lun_uuid',
                                              reason=_('uuid not found'))

        return lun_info['uuid']

    def _get_lun_status(self, lun_name):
        if not lun_name:
            err = _('Param [lun_name] is invalid.')
            raise exception.InvalidParameterValue(err=err)

        try:
            lun_info = self._get_lun_info(lun_name,
                                          ['status', 'is_action_locked'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to _get_lun_status. [%s]', lun_name)

        if not self.check_value_valid(lun_info, ['status'], string_types):
            raise exception.MalformedResponse(cmd='_get_lun_status',
                                              reason=_('status not found'))
        if not self.check_value_valid(lun_info, ['is_action_locked'], bool):
            raise exception.MalformedResponse(cmd='_get_lun_status',
                                              reason=_('action_locked '
                                                       'not found'))

        return lun_info['status'], lun_info['is_action_locked']

    def _get_snapshot_info(self, snapshot_uuid, additional=None):
        if not snapshot_uuid:
            err = _('Param [snapshot_uuid] is invalid.')
            raise exception.InvalidParameterValue(err=err)

        params = {'snapshot_uuid': snapshot_uuid}
        if additional is not None:
            params['additional'] = additional

        try:
            out = self.exec_webapi('SYNO.Core.ISCSI.LUN',
                                   'get_snapshot',
                                   1,
                                   **params)

            self.check_response(out, snapshot_id=snapshot_uuid)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to _get_snapshot_info. [%s]',
                              snapshot_uuid)

        if not self.check_value_valid(out, ['data', 'snapshot'], object):
            raise exception.MalformedResponse(cmd='_get_snapshot_info',
                                              reason=_('snapshot info not '
                                                       'found'))

        return out['data']['snapshot']

    def _get_snapshot_status(self, snapshot_uuid):
        if not snapshot_uuid:
            err = _('Param [snapshot_uuid] is invalid.')
            raise exception.InvalidParameterValue(err=err)

        try:
            snapshot_info = self._get_snapshot_info(snapshot_uuid,
                                                    ['status',
                                                     'is_action_locked'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to _get_snapshot_info. [%s]',
                              snapshot_uuid)

        if not self.check_value_valid(snapshot_info, ['status'], string_types):
            raise exception.MalformedResponse(cmd='_get_snapshot_status',
                                              reason=_('status not found'))
        if not self.check_value_valid(snapshot_info,
                                      ['is_action_locked'],
                                      bool):
            raise exception.MalformedResponse(cmd='_get_snapshot_status',
                                              reason=_('action_locked '
                                                       'not found'))

        return snapshot_info['status'], snapshot_info['is_action_locked']

    def _get_metadata_value(self, obj, key):
        if key not in obj['metadata']:
            if isinstance(obj, volume.Volume):
                raise exception.VolumeMetadataNotFound(
                    volume_id=obj['id'],
                    metadata_key=key)
            elif isinstance(obj, snapshot.Snapshot):
                raise exception.SnapshotMetadataNotFound(
                    snapshot_id=obj['id'],
                    metadata_key=key)
            else:
                raise exception.MetadataAbsent()

        return obj['metadata'][key]

    def _get_backend_name(self):
        return self.config.safe_get('volume_backend_name') or 'Synology'

    def _target_create(self, identifier):
        if not identifier:
            err = _('Param [identifier] is invalid.')
            raise exception.InvalidParameterValue(err=err)

        # 0 for no auth, 1 for single chap, 2 for mutual chap
        auth_type = 0
        chap_username = ''
        chap_password = ''
        provider_auth = ''
        if self.config.safe_get('use_chap_auth') and self.config.use_chap_auth:
            auth_type = 1
            chap_username = (self.config.safe_get('chap_username') or
                             volume_utils.generate_username(12))
            chap_password = (self.config.safe_get('chap_password') or
                             volume_utils.generate_password())
            provider_auth = ' '.join(('CHAP', chap_username, chap_password))

        trg_prefix = self.config.safe_get('target_prefix')
        trg_name = (self.TARGET_NAME_PREFIX + '%s') % identifier
        iqn = trg_prefix + trg_name

        try:
            out = self.exec_webapi('SYNO.Core.ISCSI.Target',
                                   'create',
                                   1,
                                   name=trg_name,
                                   iqn=iqn,
                                   auth_type=auth_type,
                                   user=chap_username,
                                   password=chap_password,
                                   max_sessions=0)

            self.check_response(out)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to _target_create. [%s]',
                              identifier)

        if not self.check_value_valid(out, ['data', 'target_id']):
            msg = _('Failed to get target_id of target [%s]') % trg_name
            raise exception.VolumeDriverException(message=msg)

        trg_id = out['data']['target_id']

        return iqn, trg_id, provider_auth

    def _target_delete(self, trg_id):
        if 0 > trg_id:
            err = _('trg_id is invalid: %d.') % trg_id
            raise exception.InvalidParameterValue(err=err)

        try:
            out = self.exec_webapi('SYNO.Core.ISCSI.Target',
                                   'delete',
                                   1,
                                   target_id=('%d' % trg_id))

            self.check_response(out)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to _target_delete. [%d]', trg_id)

    # is_map True for map, False for ummap
    def _lun_map_unmap_target(self, volume_name, is_map, trg_id):
        if 0 > trg_id:
            err = _('trg_id is invalid: %d.') % trg_id
            raise exception.InvalidParameterValue(err=err)

        try:
            lun_uuid = self._get_lun_uuid(volume_name)
            out = self.exec_webapi('SYNO.Core.ISCSI.LUN',
                                   'map_target' if is_map else 'unmap_target',
                                   1,
                                   uuid=lun_uuid,
                                   target_ids=['%d' % trg_id])

            self.check_response(out)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to _lun_map_unmap_target. '
                              '[%(action)s][%(vol)s].',
                              {'action': ('map_target' if is_map
                                          else 'unmap_target'),
                               'vol': volume_name})

    def _lun_map_target(self, volume_name, trg_id):
        self._lun_map_unmap_target(volume_name, True, trg_id)

    def _lun_unmap_target(self, volume_name, trg_id):
        self._lun_map_unmap_target(volume_name, False, trg_id)

    def _modify_lun_name(self, name, new_name):
        try:
            out = self.exec_webapi('SYNO.Core.ISCSI.LUN',
                                   'set',
                                   1,
                                   uuid=name,
                                   new_name=new_name)

            self.check_response(out)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to _modify_lun_name [%s].', name)

    def _check_lun_status_normal(self, volume_name):
        status = ''
        try:
            while True:
                status, locked = self._get_lun_status(volume_name)
                if not locked:
                    break
                eventlet.sleep(2)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to get lun status. [%s]',
                              volume_name)

        LOG.debug('Lun [%(vol)s], status [%(status)s].',
                  {'vol': volume_name,
                   'status': status})
        return status == 'normal'

    def _check_snapshot_status_healthy(self, snapshot_uuid):
        status = ''
        try:
            while True:
                status, locked = self._get_snapshot_status(snapshot_uuid)
                if not locked:
                    break
                eventlet.sleep(2)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to get snapshot status. [%s]',
                              snapshot_uuid)

        LOG.debug('Lun [%(snapshot)s], status [%(status)s].',
                  {'snapshot': snapshot_uuid,
                   'status': status})
        return status == 'Healthy'

    def _check_storage_response(self, out, **kwargs):
        data = 'internal error'
        exc = exception.VolumeBackendAPIException(data=data)
        message = 'Internal error'

        return (message, exc)

    def _check_iscsi_response(self, out, **kwargs):
        LUN_BAD_LUN_UUID = 18990505
        LUN_NO_SUCH_SNAPSHOT = 18990532

        if not self.check_value_valid(out, ['error', 'code'], int):
            raise exception.MalformedResponse(cmd='_check_iscsi_response',
                                              reason=_('no error code found'))

        code = out['error']['code']
        exc = None
        message = ''

        if code == LUN_BAD_LUN_UUID:
            exc = SynoLUNNotExist(**kwargs)
            message = 'Bad LUN UUID'
        elif code == LUN_NO_SUCH_SNAPSHOT:
            exc = exception.SnapshotNotFound(**kwargs)
            message = 'No such snapshot'
        else:
            data = 'internal error'
            exc = exception.VolumeBackendAPIException(data=data)
            message = 'Internal error'

        message = '%s [%d]' % (message, code)

        return (message, exc)

    def _check_ds_pool_status(self):
        pool_info = self._get_pool_info()
        if not self.check_value_valid(pool_info, ['readonly'], bool):
            raise exception.MalformedResponse(cmd='_check_ds_pool_status',
                                              reason=_('no readonly found'))

        if pool_info['readonly']:
            message = (_('pool [%s] is not writable') %
                       self.config.synology_pool_name)
            raise exception.VolumeDriverException(message=message)

    def _check_ds_version(self):
        try:
            out = self.exec_webapi('SYNO.Core.System',
                                   'info',
                                   1,
                                   type='firmware')

            self.check_response(out)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to _check_ds_version')

        if not self.check_value_valid(out,
                                      ['data', 'firmware_ver'],
                                      string_types):
            raise exception.MalformedResponse(cmd='_check_ds_version',
                                              reason=_('data not found'))
        firmware_version = out['data']['firmware_ver']

        # e.g. 'DSM 6.1-7610', 'DSM 6.0.1-7321 update 3', 'DSM UC 1.0-6789'
        pattern = re.compile(r"^(.*) (\d+)\.(\d+)(?:\.(\d+))?-(\d+)"
                             r"(?: [uU]pdate (\d+))?$")
        matches = pattern.match(firmware_version)

        if not matches:
            m = (_('DS version %s is not supported') %
                 firmware_version)
            raise exception.VolumeDriverException(message=m)

        os_name = matches.group(1)
        major = int(matches.group(2))
        minor = int(matches.group(3))
        hotfix = int(matches.group(4)) if matches.group(4) else 0

        if os_name == 'DSM UC':
            return
        elif (os_name == 'DSM' and
                ((6 > major) or (major == 6 and minor == 0 and hotfix < 2))):
            m = (_('DS version %s is not supported') %
                 firmware_version)
            raise exception.VolumeDriverException(message=m)

    def _check_ds_ability(self):
        try:
            out = self.exec_webapi('SYNO.Core.System',
                                   'info',
                                   1,
                                   type='define')

            self.check_response(out)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to _check_ds_ability')

        if not self.check_value_valid(out, ['data'], dict):
            raise exception.MalformedResponse(cmd='_check_ds_ability',
                                              reason=_('data not found'))
        define = out['data']

        if 'usbstation' in define and define['usbstation'] == 'yes':
            m = _('usbstation is not supported')
            raise exception.VolumeDriverException(message=m)

        if ('support_storage_mgr' not in define
                or define['support_storage_mgr'] != 'yes'):
            m = _('Storage Manager is not supported in DS')
            raise exception.VolumeDriverException(message=m)

        if ('support_iscsi_target' not in define
                or define['support_iscsi_target'] != 'yes'):
            m = _('iSCSI target feature is not supported in DS')
            raise exception.VolumeDriverException(message=m)

        if ('support_vaai' not in define
                or define['support_vaai'] != 'yes'):
            m = _('VAAI feature is not supported in DS')
            raise exception.VolumeDriverException(message=m)

        if ('supportsnapshot' not in define
                or define['supportsnapshot'] != 'yes'):
            m = _('Snapshot feature is not supported in DS')
            raise exception.VolumeDriverException(message=m)

    def check_response(self, out, **kwargs):
        if out['success']:
            return

        data = 'internal error'
        exc = exception.VolumeBackendAPIException(data=data)
        message = 'Internal error'

        api = out['api_info']['api']

        if (api.startswith('SYNO.Core.ISCSI.')):
            message, exc = self._check_iscsi_response(out, **kwargs)
        elif (api.startswith('SYNO.Core.Storage.')):
            message, exc = self._check_storage_response(out, **kwargs)

        LOG.exception('%(message)s', {'message': message})

        raise exc

    def exec_webapi(self, api, method, version, **kwargs):
        result = self.synoexec(api, method, version, **kwargs)

        if 'http_status' in result and 200 != result['http_status']:
            raise SynoAPIHTTPError(code=result['http_status'])

        result['api_info'] = {'api': api,
                              'method': method,
                              'version': version}
        return result

    def check_value_valid(self, obj, key_array, value_type=None):
        curr_obj = obj
        for key in key_array:
            if key not in curr_obj:
                LOG.error('key [%(key)s] is not in %(obj)s',
                          {'key': key,
                           'obj': curr_obj})
                return False
            curr_obj = curr_obj[key]

        if value_type and not isinstance(curr_obj, value_type):
            LOG.error('[%(obj)s] is %(type)s, not %(value_type)s',
                      {'obj': curr_obj,
                       'type': type(curr_obj),
                       'value_type': value_type})
            return False

        return True

    def get_ip(self):
        return self.config.target_ip_address

    def get_provider_location(self, iqn, trg_id):
        portals = ['%(ip)s:%(port)d' % {'ip': self.get_ip(),
                                        'port': self.target_port}]
        sec_ips = self.config.safe_get('iscsi_secondary_ip_addresses')
        for ip in sec_ips:
            portals.append('%(ip)s:%(port)d' %
                           {'ip': ip,
                            'port': self.target_port})

        return '%s,%d %s 0' % (
            ';'.join(portals),
            trg_id,
            iqn)

    def is_lun_mapped(self, lun_name):
        if not lun_name:
            err = _('Param [lun_name] is invalid.')
            raise exception.InvalidParameterValue(err=err)

        try:
            lun_info = self._get_lun_info(lun_name, ['is_mapped'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to _is_lun_mapped. [%s]', lun_name)

        if not self.check_value_valid(lun_info, ['is_mapped'], bool):
            raise exception.MalformedResponse(cmd='_is_lun_mapped',
                                              reason=_('is_mapped not found'))

        return lun_info['is_mapped']

    def check_for_setup_error(self):
        self._check_ds_pool_status()
        self._check_ds_version()
        self._check_ds_ability()

    def update_volume_stats(self):
        """Update volume statistics.

        Three kinds of data are stored on the Synology backend pool:
        1. Thin volumes (LUNs on the pool),
        2. Thick volumes (LUNs on the pool),
        3. Other user data.

        other_user_data_gb is the size of the 3rd one.
        lun_provisioned_gb is the summation of all thin/thick volume
        provisioned size.

        Only thin type is available for Cinder volumes.
        """

        free_gb, total_gb, other_user_data_gb = self._get_pool_size()
        lun_provisioned_gb = self._get_pool_lun_provisioned_size()

        data = {}
        data['volume_backend_name'] = self.volume_backend_name
        data['vendor_name'] = self.vendor_name
        data['storage_protocol'] = self.config.target_protocol
        data['consistencygroup_support'] = False
        data['QoS_support'] = False
        data['thin_provisioning_support'] = True
        data['thick_provisioning_support'] = False
        data['reserved_percentage'] = self.config.reserved_percentage

        data['free_capacity_gb'] = free_gb
        data['total_capacity_gb'] = total_gb
        data['provisioned_capacity_gb'] = (lun_provisioned_gb +
                                           other_user_data_gb)
        data['max_over_subscription_ratio'] = (self.config.
                                               max_over_subscription_ratio)

        data['target_ip_address'] = self.config.target_ip_address
        data['pool_name'] = self.config.synology_pool_name
        data['backend_info'] = ('%s:%s:%s' %
                                (self.vendor_name,
                                 self.driver_type,
                                 self.host_uuid))

        return data

    def create_volume(self, volume):
        try:
            out = self.exec_webapi('SYNO.Core.ISCSI.LUN',
                                   'create',
                                   1,
                                   name=volume['name'],
                                   type=self.CINDER_LUN,
                                   location=('/' +
                                             self.config.synology_pool_name),
                                   size=volume['size'] * units.Gi)

            self.check_response(out)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to create_volume. [%s]',
                              volume['name'])

        if not self._check_lun_status_normal(volume['name']):
            message = _('Lun [%s] status is not normal') % volume['name']
            raise exception.VolumeDriverException(message=message)

    def delete_volume(self, volume):
        try:
            lun_uuid = self._get_lun_uuid(volume['name'])
            out = self.exec_webapi('SYNO.Core.ISCSI.LUN',
                                   'delete',
                                   1,
                                   uuid=lun_uuid)

            self.check_response(out)

        except SynoLUNNotExist:
            LOG.warning('LUN does not exist')
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to delete_volume. [%s]',
                              volume['name'])

    def create_cloned_volume(self, volume, src_vref):
        try:
            src_lun_uuid = self._get_lun_uuid(src_vref['name'])
            out = self.exec_webapi('SYNO.Core.ISCSI.LUN',
                                   'clone',
                                   1,
                                   src_lun_uuid=src_lun_uuid,
                                   dst_lun_name=volume['name'],
                                   is_same_pool=True,
                                   clone_type='CINDER')
            self.check_response(out)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to create_cloned_volume. [%s]',
                              volume['name'])

        if not self._check_lun_status_normal(volume['name']):
            message = _('Lun [%s] status is not normal.') % volume['name']
            raise exception.VolumeDriverException(message=message)

        if src_vref['size'] < volume['size']:
            self.extend_volume(volume, volume['size'])

    def extend_volume(self, volume, new_size):
        try:
            lun_uuid = self._get_lun_uuid(volume['name'])
            out = self.exec_webapi('SYNO.Core.ISCSI.LUN',
                                   'set',
                                   1,
                                   uuid=lun_uuid,
                                   new_size=new_size * units.Gi)

            self.check_response(out)

        except Exception as e:
            LOG.exception('Failed to extend_volume. [%s]',
                          volume['name'])
            raise exception.ExtendVolumeError(reason=e.msg)

    def update_migrated_volume(self, volume, new_volume):
        try:
            self._modify_lun_name(new_volume['name'], volume['name'])
        except Exception:
            reason = _('Failed to _modify_lun_name [%s].') % new_volume['name']
            raise exception.VolumeMigrationFailed(reason=reason)

        return {'_name_id': None}

    def create_snapshot(self, snapshot):
        desc = '(Cinder) ' + (snapshot['id'] or '')

        try:
            resp = self.exec_webapi('SYNO.Core.ISCSI.LUN',
                                    'take_snapshot',
                                    1,
                                    src_lun_uuid=snapshot['volume']['name'],
                                    is_app_consistent=False,
                                    is_locked=False,
                                    taken_by='Cinder',
                                    description=desc)

            self.check_response(resp)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to create_snapshot. [%s]',
                              snapshot['volume']['name'])

        if not self.check_value_valid(resp,
                                      ['data', 'snapshot_uuid'],
                                      string_types):
            raise exception.MalformedResponse(cmd='create_snapshot',
                                              reason=_('uuid not found'))

        snapshot_uuid = resp['data']['snapshot_uuid']
        if not self._check_snapshot_status_healthy(snapshot_uuid):
            message = (_('Volume [%(vol)s] snapshot [%(snapshot)s] status '
                         'is not healthy.') %
                       {'vol': snapshot['volume']['name'],
                        'snapshot': snapshot_uuid})
            raise exception.VolumeDriverException(message=message)

        metadata = snapshot['metadata']
        metadata.update({
            self.METADATA_DS_SNAPSHOT_UUID: snapshot_uuid
        })

        return {'metadata': metadata}

    def delete_snapshot(self, snapshot):
        try:
            ds_snapshot_uuid = (self._get_metadata_value
                                (snapshot, self.METADATA_DS_SNAPSHOT_UUID))

            out = self.exec_webapi('SYNO.Core.ISCSI.LUN',
                                   'delete_snapshot',
                                   1,
                                   snapshot_uuid=ds_snapshot_uuid,
                                   deleted_by='Cinder')

            self.check_response(out, snapshot_id=snapshot['id'])

        except (exception.SnapshotNotFound,
                exception.SnapshotMetadataNotFound):
            return
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to delete_snapshot. [%s]',
                              snapshot['id'])

    def create_volume_from_snapshot(self, volume, snapshot):
        try:
            ds_snapshot_uuid = (self._get_metadata_value
                                (snapshot, self.METADATA_DS_SNAPSHOT_UUID))

            out = self.exec_webapi('SYNO.Core.ISCSI.LUN',
                                   'clone_snapshot',
                                   1,
                                   src_lun_uuid=snapshot['volume']['name'],
                                   snapshot_uuid=ds_snapshot_uuid,
                                   cloned_lun_name=volume['name'],
                                   clone_type='CINDER')

            self.check_response(out)

        except exception.SnapshotMetadataNotFound:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to get snapshot UUID. [%s]',
                              snapshot['id'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to create_volume_from_snapshot. [%s]',
                              snapshot['id'])

        if not self._check_lun_status_normal(volume['name']):
            message = (_('Volume [%(vol)s] snapshot [%(snapshot)s] status '
                         'is not healthy.') %
                       {'vol': snapshot['volume']['name'],
                        'snapshot': ds_snapshot_uuid})
            raise exception.VolumeDriverException(message=message)

        if snapshot['volume_size'] < volume['size']:
            self.extend_volume(volume, volume['size'])

    def get_iqn_and_trgid(self, location):
        if not location:
            err = _('Param [location] is invalid.')
            raise exception.InvalidParameterValue(err=err)

        result = location.split(' ')
        if len(result) < 2:
            raise exception.InvalidInput(reason=location)

        data = result[0].split(',')
        if len(data) < 2:
            raise exception.InvalidInput(reason=location)

        iqn = result[1]
        trg_id = data[1]

        return iqn, int(trg_id, 10)

    def get_iscsi_properties(self, volume):
        if not volume['provider_location']:
            err = _("Param volume['provider_location'] is invalid.")
            raise exception.InvalidParameterValue(err=err)

        iqn, trg_id = self.get_iqn_and_trgid(volume['provider_location'])

        iscsi_properties = {
            'target_discovered': False,
            'target_iqn': iqn,
            'target_portal': '%(ip)s:%(port)d' % {'ip': self.get_ip(),
                                                  'port': self.target_port},
            'volume_id': volume['id'],
            'access_mode': 'rw',
            'discard': False
        }
        ips = self.config.safe_get('iscsi_secondary_ip_addresses')
        if ips:
            target_portals = [iscsi_properties['target_portal']]
            for ip in ips:
                target_portals.append('%(ip)s:%(port)d' %
                                      {'ip': ip,
                                       'port': self.target_port})
            iscsi_properties.update(target_portals=target_portals)
            count = len(target_portals)
            iscsi_properties.update(target_iqns=[
                iscsi_properties['target_iqn']
            ] * count)
            iscsi_properties.update(target_lun=0)
            iscsi_properties.update(target_luns=[
                iscsi_properties['target_lun']
            ] * count)

        if 'provider_auth' in volume:
            auth = volume['provider_auth']
            if auth:
                try:
                    (auth_method, auth_username, auth_password) = auth.split()
                    iscsi_properties['auth_method'] = auth_method
                    iscsi_properties['auth_username'] = auth_username
                    iscsi_properties['auth_password'] = auth_password
                except Exception:
                    LOG.error('Invalid provider_auth: %s', auth)

        return iscsi_properties

    def create_iscsi_export(self, volume_name, identifier):
        iqn, trg_id, provider_auth = self._target_create(identifier)
        self._lun_map_target(volume_name, trg_id)

        return iqn, trg_id, provider_auth

    def remove_iscsi_export(self, volume_name, trg_id):
        self._lun_unmap_target(volume_name, trg_id)
        self._target_delete(trg_id)
