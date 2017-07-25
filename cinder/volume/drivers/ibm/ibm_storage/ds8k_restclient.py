#  Copyright (c) 2016 IBM Corporation
#  All Rights Reserved.
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
#
import abc
import eventlet
import importlib
import json
import six
from six.moves import urllib

import requests
from requests import exceptions as req_exception

from cinder import exception
from cinder.i18n import _

TOKEN_ERROR_CODES = ('BE7A001B', 'BE7A001A')
# remove BE7A0032 after REST fixed the problem of throwing message
# which shows all LSS are full but actually only one LSS is full.
LSS_ERROR_CODES = ('BE7A0031', 'BE7A0032')
AUTHENTICATION_ERROR_CODES = (
    'BE7A001B', 'BE7A001A', 'BE7A0027',
    'BE7A0028', 'BE7A0029', 'BE7A002A',
    'BE7A002B', 'BE7A002C', 'BE7A002D'
)


class APIException(exception.VolumeBackendAPIException):
    """Exception raised for errors in the REST APIs."""

    """
    Attributes:
        message -- explanation of the error
    """
    pass


class APIAuthenticationException(APIException):
    """Exception raised for errors in the Authentication."""

    """
    Attributes:
        message -- explanation of the error
    """
    pass


class LssFullException(APIException):
    """Exception raised for errors when LSS is full."""

    """
    Attributes:
        message -- explanation of the error
    """
    pass


class LssIDExhaustError(exception.VolumeBackendAPIException):
    """Exception raised for errors when can not find available LSS."""

    """
    Attributes:
        message -- explanation of the error
    """
    pass


class TimeoutException(APIException):
    """Exception raised when the request is time out."""

    """
    Attributes:
        message -- explanation of the error
    """
    pass


@six.add_metaclass(abc.ABCMeta)
class AbstractRESTConnector(object):
    """Inherit this class when you define your own connector."""

    @abc.abstractmethod
    def close(self):
        """close the connector.

        If the connector uses persistent connection, please provide
        a way to close it in this method, otherwise you can just leave
        this method empty.

        Input: None
        Output: None
        Exception: can raise any exceptions
        """
        pass

    @abc.abstractmethod
    def send(self, method='', url='', headers=None, payload='', timeout=900):
        """send the request.

        Input: see above
        Output:

            if we reached the server and read an HTTP response:

            .. code:: text

              (INTEGER__HTTP_RESPONSE_STATUS_CODE,
               STRING__BODY_OF_RESPONSE_EVEN_IF_STATUS_NOT_200)

            if we were not able to reach the server or response
            was invalid HTTP(like certificate error, or could not
            resolve domain etc):

            .. code:: text

              (False, STRING__SHORT_EXPLANATION_OF_REASON_FOR_NOT_
               REACHING_SERVER_OR_GETTING_INVALID_RESPONSE)

        Exception: should not raise any exceptions itself as all
            the expected scenarios are covered above. Unexpected
            exceptions are permitted.

        """
        pass


class DefaultRESTConnector(AbstractRESTConnector):
    """User can write their own connector and pass it to RESTScheduler."""

    def __init__(self, verify):
        # overwrite certificate validation method only when using
        # default connector, and not globally import the new scheme.
        if isinstance(verify, six.string_types):
            importlib.import_module("cinder.volume.drivers.ibm.ibm_storage."
                                    "ds8k_connection")
        self.session = None
        self.verify = verify

    def connect(self):
        if self.session is None:
            self.session = requests.Session()
            if isinstance(self.verify, six.string_types):
                self.session.mount('httpsds8k://',
                                   requests.adapters.HTTPAdapter())
            else:
                self.session.mount('https://',
                                   requests.adapters.HTTPAdapter())
            self.session.verify = self.verify

    def close(self):
        self.session.close()
        self.session = None

    def send(self, method='', url='', headers=None, payload='', timeout=900):
        self.connect()
        try:
            if isinstance(self.verify, six.string_types):
                url = url.replace('https://', 'httpsds8k://')
            resp = self.session.request(method,
                                        url,
                                        headers=headers,
                                        data=payload,
                                        timeout=timeout)
            return resp.status_code, resp.text
        except req_exception.ConnectTimeout as e:
            self.close()
            return 408, "Connection time out: %s" % six.text_type(e)
        except req_exception.SSLError as e:
            self.close()
            return False, "SSL error: %s" % six.text_type(e)
        except Exception as e:
            self.close()
            return False, "Unexcepted exception: %s" % six.text_type(e)


class RESTScheduler(object):
    """This class is multithread friendly.

    it isn't optimally (token handling) but good enough for low-mid traffic.
    """

    def __init__(self, host, user, passw, connector_obj, verify=False):
        if not host:
            raise APIException('The host parameter must not be empty.')
        # the api incorrectly transforms an empty password to a missing
        # password paramter, so we have to catch it here
        if not user or not passw:
            raise APIAuthenticationException(
                _('The username and the password parameters must '
                  'not be empty.'))
        self.token = ''
        self.host = host
        self.port = '8452'
        self.user = user
        self.passw = passw
        self.connector = connector_obj or DefaultRESTConnector(verify)
        self.connect()

    def connect(self):
        # one retry when connecting, 60s should be enough to get the token,
        # usually it is within 30s.
        try:
            response = self.send(
                'POST', '/tokens',
                {'username': self.user, 'password': self.passw},
                timeout=60)
        except Exception:
            eventlet.sleep(2)
            response = self.send(
                'POST', '/tokens',
                {'username': self.user, 'password': self.passw},
                timeout=60)
        self.token = response['token']['token']

    def close(self):
        self.connector.close()

    # usually NI responses within 15min.
    def send(self, method, endpoint, data=None, badStatusException=True,
             params=None, fields=None, timeout=900):
        # verify the method
        if method not in ('GET', 'POST', 'PUT', 'DELETE'):
            msg = _("Invalid HTTP method: %s") % method
            raise APIException(data=msg)

        # prepare the url
        url = "https://%s:%s/api/v1%s" % (self.host, self.port, endpoint)
        if fields:
            params = params or {}
            params['data_fields'] = ','.join(fields)
        if params:
            url += (('&' if '?' in url else '?') +
                    urllib.parse.urlencode(params))

        # prepare the data
        data = json.dumps({'request': {'params': data}}) if data else None
        # make a REST request to DS8K and get one retry if logged out
        for attempts in range(2):
            headers = {'Content-Type': 'application/json',
                       'X-Auth-Token': self.token}
            code, body = self.connector.send(method, url, headers,
                                             data, timeout)
            # parse the returned code
            if code == 200:
                try:
                    response = json.loads(body)
                except ValueError:
                    response = {'server': {
                        'status': 'failed',
                        'message': 'Unable to parse server response into json.'
                    }}
            elif code == 408:
                response = {'server': {'status': 'timeout', 'message': body}}
            elif code is not False:
                try:
                    response = json.loads(body)
                    # make sure has useful message
                    response['server']['message']
                except Exception:
                    response = {'server': {
                        'status': 'failed',
                        'message': 'HTTP %s: %s' % (code, body)
                    }}
            else:
                response = {'server': {'status': 'failed', 'message': body}}

            # handle the response
            if (response['server'].get('code') in TOKEN_ERROR_CODES and
                    attempts == 0):
                self.connect()
            elif response['server'].get('code') in AUTHENTICATION_ERROR_CODES:
                raise APIAuthenticationException(
                    data=(_('Authentication failed for host %(host)s. '
                            'Exception= %(e)s') %
                          {'host': self.host,
                           'e': response['server']['message']}))
            elif response['server'].get('code') in LSS_ERROR_CODES:
                raise LssFullException(
                    data=(_('Can not put the volume in LSS: %s')
                          % response['server']['message']))
            elif response['server']['status'] == 'timeout':
                raise TimeoutException(
                    data=(_('Request to storage API time out: %s')
                          % response['server']['message']))
            elif (response['server']['status'] != 'ok' and
                  (badStatusException or 'code' not in response['server'])):
                # if code is not in response means that error was in
                # transport so we raise exception even if asked not to
                # via badStatusException=False, but will retry it to
                # confirm the problem.
                if attempts == 1:
                    raise APIException(
                        data=(_("Request to storage API failed: %(err)s, "
                                "(%(url)s).")
                              % {'err': response['server']['message'],
                                 'url': url}))
                eventlet.sleep(2)
            else:
                return response

    # same as the send method above but returns first item from
    # response data, must receive only one item.
    def fetchall(self, *args, **kwargs):
        r = self.send(*args, **kwargs)['data']
        if len(r) != 1:
            raise APIException(
                data=(_('Expected one result but got %d.') % len(r)))
        else:
            return r.popitem()[1]

    # the api for some reason returns a list when you request details
    # of a specific item.
    def fetchone(self, *args, **kwargs):
        r = self.fetchall(*args, **kwargs)
        if len(r) != 1:
            raise APIException(
                data=(_('Expected one item in result but got %d.') % len(r)))
        return r[0]

    # same as the send method above but returns the last element of the
    # link property in the response.
    def fetchid(self, *args, **kwargs):
        r = self.send(*args, **kwargs)
        if 'responses' in r:
            if len(r['responses']) != 1:
                raise APIException(
                    data=(_('Expected one item in result responses but '
                            'got %d.') % len(r['responses'])))
            r = r['responses'][0]
        return r['link']['href'].split('/')[-1]

    # the api unfortunately has no way to differentiate between api error
    # and error in DS8K resources. this method returns True if "ok", False
    # if "failed", exception otherwise.
    def statusok(self, *args, **kwargs):
        return self.send(*args, badStatusException=False,
                         **kwargs)['server']['status'] == 'ok'
