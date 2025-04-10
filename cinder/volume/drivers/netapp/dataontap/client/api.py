# Copyright (c) 2012 NetApp, Inc.  All rights reserved.
# Copyright (c) 2014 Navneet Singh.  All rights reserved.
# Copyright (c) 2014 Glenn Gobeli.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2015 Alex Meade.  All rights reserved.
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
"""NetApp API for Data ONTAP and OnCommand DFM.

Contains classes required to issue API calls to Data ONTAP and OnCommand DFM.
"""
import random
import ssl
import urllib


from eventlet import greenthread
from eventlet import semaphore
from lxml import etree
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import netutils
import requests
from requests.adapters import HTTPAdapter
from requests import auth
from requests.packages.urllib3.util.retry import Retry

from cinder import exception
from cinder.i18n import _
from cinder import ssh_utils
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)

# ZAPI API error codes.
EAPIERROR = '13001'
EAPIPRIVILEGE = '13003'
EAPINOTFOUND = '13005'
ESNAPSHOTNOTALLOWED = '13023'
ESIS_CLONE_NOT_LICENSED = '14956'
EOBJECTNOTFOUND = '15661'
ESOURCE_IS_DIFFERENT = '17105'
ERELATION_EXISTS = '17122'
ERELATION_NOT_QUIESCED = '17127'
ENOTRANSFER_IN_PROGRESS = '17130'
EANOTHER_OP_ACTIVE = '17131'
ETRANSFER_IN_PROGRESS = '17137'


class NaServer(object):
    """Encapsulates server connection logic."""

    TRANSPORT_TYPE_HTTP = 'http'
    TRANSPORT_TYPE_HTTPS = 'https'
    SERVER_TYPE_FILER = 'filer'
    SERVER_TYPE_DFM = 'dfm'
    URL_FILER = 'servlets/netapp.servlets.admin.XMLrequest_filer'
    URL_DFM = 'apis/XMLrequest'
    NETAPP_NS = 'http://www.netapp.com/filer/admin'

    def __init__(self, host, server_type=SERVER_TYPE_FILER,
                 transport_type=TRANSPORT_TYPE_HTTP,
                 username=None,
                 password=None, port=None, api_trace_pattern=None,
                 private_key_file=None, certificate_file=None,
                 ca_certificate_file=None, certificate_host_validation=None):
        self._host = host
        self.set_server_type(server_type)
        self.set_transport_type(transport_type)
        if port:
            self.set_port(port)
        self._username = username
        self._password = password
        self._private_key_file = private_key_file
        self._certificate_file = certificate_file
        self._ca_certificate_file = ca_certificate_file
        self._certificate_host_validation = certificate_host_validation
        self._refresh_conn = True

        if api_trace_pattern is not None:
            na_utils.setup_api_trace_pattern(api_trace_pattern)

        LOG.debug('Using NetApp controller: %s', self._host)

    def set_transport_type(self, transport_type):
        """Set the transport type protocol for API.

        Supports http and https transport types.
        """
        if not transport_type:
            raise ValueError('No transport type specified')
        if transport_type.lower() not in (
                NaServer.TRANSPORT_TYPE_HTTP,
                NaServer.TRANSPORT_TYPE_HTTPS):
            raise ValueError('Unsupported transport type')
        self._protocol = transport_type.lower()
        if self._protocol == NaServer.TRANSPORT_TYPE_HTTP:
            if self._server_type == NaServer.SERVER_TYPE_FILER:
                self.set_port(80)
            else:
                self.set_port(8088)
        else:
            if self._server_type == NaServer.SERVER_TYPE_FILER:
                self.set_port(443)
            else:
                self.set_port(8488)
        self._refresh_conn = True

    def set_style(self, style):
        """Set the authorization style for communicating with the server.

        Supports basic_auth for now. Certificate_auth mode to be done.
        """
        if style.lower() not in (NaServer.STYLE_LOGIN_PASSWORD,
                                 NaServer.STYLE_CERTIFICATE):
            raise ValueError('Unsupported authentication style')
        self._auth_style = style.lower()

    def set_server_type(self, server_type):
        """Set the target server type.

        Supports filer and dfm server types.
        """
        if server_type.lower() not in (NaServer.SERVER_TYPE_FILER,
                                       NaServer.SERVER_TYPE_DFM):
            raise ValueError('Unsupported server type')
        self._server_type = server_type.lower()
        if self._server_type == NaServer.SERVER_TYPE_FILER:
            self._url = NaServer.URL_FILER
        else:
            self._url = NaServer.URL_DFM
        self._ns = NaServer.NETAPP_NS
        self._refresh_conn = True

    def set_ontap_version(self, version):
        self._ontap_version = version

    def get_ontap_version(self):
        return self._ontap_version

    def set_api_version(self, major, minor):
        """Set the API version."""
        try:
            self._api_major_version = int(major)
            self._api_minor_version = int(minor)
            self._api_version = str(major) + "." + str(minor)
        except ValueError:
            raise ValueError('Major and minor versions must be integers')
        self._refresh_conn = True

    def get_api_version(self):
        """Gets the API version tuple."""
        if hasattr(self, '_api_version'):
            return (self._api_major_version, self._api_minor_version)
        return None

    def set_port(self, port):
        """Set the server communication port."""
        try:
            int(port)
        except ValueError:
            raise ValueError('Port must be integer')
        self._port = str(port)
        self._refresh_conn = True

    def set_timeout(self, seconds):
        """Sets the timeout in seconds."""
        try:
            self._timeout = int(seconds)
        except ValueError:
            raise ValueError('timeout in seconds must be integer')

    def set_vfiler(self, vfiler):
        """Set the vfiler to use if tunneling gets enabled."""
        self._vfiler = vfiler

    def set_vserver(self, vserver):
        """Set the vserver to use if tunneling gets enabled."""
        self._vserver = vserver

    @volume_utils.trace_api(filter_function=na_utils.trace_filter_func_api)
    def send_http_request(self, na_element, enable_tunneling=False):
        """Invoke the API on the server."""
        if not na_element or not isinstance(na_element, NaElement):
            raise ValueError('NaElement must be supplied to invoke API')
        request, request_element = self._create_request(na_element,
                                                        enable_tunneling)
        if not hasattr(self, '_opener') or not self._opener \
                or self._refresh_conn:
            self._build_opener()
        try:
            if hasattr(self, '_timeout'):
                response = self._opener.open(request, timeout=self._timeout)
            else:
                response = self._opener.open(request)
        except urllib.error.HTTPError as e:
            raise NaApiError(e.code, e.msg)
        except Exception:
            LOG.exception("Error communicating with NetApp filer.")
            raise NaApiError('Unexpected error')

        response_xml = response.read()
        response_element = self._get_result(response_xml)

        return response_element

    def invoke_successfully(self, na_element, enable_tunneling=False):
        """Invokes API and checks execution status as success.

        Need to set enable_tunneling to True explicitly to achieve it.
        This helps to use same connection instance to enable or disable
        tunneling. The vserver or vfiler should be set before this call
        otherwise tunneling remains disabled.
        """
        result = self.send_http_request(na_element, enable_tunneling)
        if result.has_attr('status') and result.get_attr('status') == 'passed':
            return result
        code = result.get_attr('errno') \
            or result.get_child_content('errorno') \
            or 'ESTATUSFAILED'
        if code == ESIS_CLONE_NOT_LICENSED:
            msg = 'Clone operation failed: FlexClone not licensed.'
        else:
            msg = result.get_attr('reason') \
                or result.get_child_content('reason') \
                or 'Execution status is failed due to unknown reason'
        raise NaApiError(code, msg)

    def send_request(self, api_name, api_args=None, enable_tunneling=True):
        """Sends request to Ontapi."""
        request = NaElement(api_name)
        if api_args:
            request.translate_struct(api_args)
        return self.invoke_successfully(request, enable_tunneling)

    def _create_request(self, na_element, enable_tunneling=False):
        """Creates request in the desired format."""
        netapp_elem = NaElement('netapp')
        netapp_elem.add_attr('xmlns', self._ns)
        if hasattr(self, '_api_version'):
            netapp_elem.add_attr('version', self._api_version)
        if enable_tunneling:
            self._enable_tunnel_request(netapp_elem)
        netapp_elem.add_child_elem(na_element)
        request_d = netapp_elem.to_string()
        request = urllib.request.Request(
            self._get_url(), data=request_d,
            headers={'Content-Type': 'text/xml', 'charset': 'utf-8'})
        return request, netapp_elem

    def _enable_tunnel_request(self, netapp_elem):
        """Enables vserver or vfiler tunneling."""
        if hasattr(self, '_vfiler') and self._vfiler:
            if hasattr(self, '_api_major_version') and \
                    hasattr(self, '_api_minor_version') and \
                    self._api_major_version >= 1 and \
                    self._api_minor_version >= 7:
                netapp_elem.add_attr('vfiler', self._vfiler)
            else:
                raise ValueError('ontapi version has to be atleast 1.7'
                                 ' to send request to vfiler')
        if hasattr(self, '_vserver') and self._vserver:
            if hasattr(self, '_api_major_version') and \
                    hasattr(self, '_api_minor_version') and \
                    self._api_major_version >= 1 and \
                    self._api_minor_version >= 15:
                netapp_elem.add_attr('vfiler', self._vserver)
            else:
                raise ValueError('ontapi version has to be atleast 1.15'
                                 ' to send request to vserver')

    def _parse_response(self, response):
        """Get the NaElement for the response."""
        if not response:
            raise NaApiError('No response received')
        xml = etree.XML(response)
        return NaElement(xml)

    def _get_result(self, response):
        """Gets the call result."""
        processed_response = self._parse_response(response)
        return processed_response.get_child_by_name('results')

    def _get_url(self):
        host = self._host

        if netutils.is_valid_ipv6(host):
            host = netutils.escape_ipv6(host)

        return '%s://%s:%s/%s' % (self._protocol, host, self._port,
                                  self._url)

    def _build_opener(self):
        if self._private_key_file and self._certificate_file:
            auth_handler = self._create_certificate_auth_handler()
        else:
            auth_handler = self._create_basic_auth_handler()
        opener = urllib.request.build_opener(auth_handler)
        self._opener = opener

    def _create_basic_auth_handler(self):
        password_man = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        password_man.add_password(None, self._get_url(), self._username,
                                  self._password)
        auth_handler = urllib.request.HTTPBasicAuthHandler(password_man)
        return auth_handler

    def _create_certificate_auth_handler(self):
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        if not self._certificate_host_validation:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        if self._certificate_file and self._private_key_file:
            context.load_cert_chain(certfile=self._certificate_file,
                                    keyfile=self._private_key_file)
            if self._ca_certificate_file:
                context.load_verify_locations(cafile=self._ca_certificate_file)
        auth_handler = urllib.request.HTTPSHandler(context=context)
        return auth_handler

    def __str__(self):
        return "server: %s" % self._host


class NaElement(object):
    """Class wraps basic building block for NetApp API request."""

    def __init__(self, name):
        """Name of the element or etree.Element."""
        if isinstance(name, etree._Element):
            self._element = name
        else:
            self._element = etree.Element(name)

    def get_name(self):
        """Returns the tag name of the element."""
        return self._element.tag

    def set_content(self, text):
        """Set the text string for the element."""
        self._element.text = text

    def get_content(self):
        """Get the text for the element."""
        return self._element.text

    def add_attr(self, name, value):
        """Add the attribute to the element."""
        self._element.set(name, value)

    def add_child_elem(self, na_element):
        """Add the child element to the element."""
        if isinstance(na_element, NaElement):
            self._element.append(na_element._element)
            return
        raise Exception(_('Failed to add child element.'))

    def get_child_by_name(self, name):
        """Get the child element by the tag name."""
        for child in self._element.iterchildren():
            if child.tag == name or etree.QName(child.tag).localname == name:
                return NaElement(child)
        return None

    def get_child_content(self, name):
        """Get the content of the child."""
        for child in self._element.iterchildren():
            if child.tag == name or etree.QName(child.tag).localname == name:
                return child.text
        return None

    def get_children(self):
        """Get the children for the element."""
        return [NaElement(el) for el in self._element.iterchildren()]

    def has_attr(self, name):
        """Checks whether element has attribute."""
        attributes = self._element.attrib or {}
        return name in attributes.keys()

    def get_attr(self, name):
        """Get the attribute with the given name."""
        attributes = self._element.attrib or {}
        return attributes.get(name)

    def get_attr_names(self):
        """Returns the list of attribute names."""
        attributes = self._element.attrib or {}
        return list(attributes.keys())

    def add_new_child(self, name, content, convert=False):
        """Add child with tag name and content.

           Convert replaces entity refs to chars.
        """
        child = NaElement(name)
        if convert:
            content = NaElement._convert_entity_refs(content)
        child.set_content(content)
        self.add_child_elem(child)

    @staticmethod
    def _convert_entity_refs(text):
        """Converts entity refs to chars to handle etree auto conversions."""
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        return text

    @staticmethod
    def create_node_with_children(node, **children):
        """Creates and returns named node with children."""
        parent = NaElement(node)
        for child in children:
            parent.add_new_child(child, children.get(child, None))
        return parent

    def add_node_with_children(self, node, **children):
        """Creates named node with children."""
        parent = NaElement.create_node_with_children(node, **children)
        self.add_child_elem(parent)

    def to_string(self, pretty=False, method='xml', encoding='UTF-8'):
        """Prints the element to string."""
        return etree.tostring(self._element, method=method, encoding=encoding,
                              pretty_print=pretty)

    def __str__(self):
        xml = self.to_string(pretty=True).decode('utf-8')
        return xml

    def __eq__(self, other):
        return str(self) == str(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(str(self))

    def __repr__(self):
        return str(self)

    def __getitem__(self, key):
        """Dict getter method for NaElement.

            Returns NaElement list if present,
            text value in case no NaElement node
            children or attribute value if present.
        """

        child = self.get_child_by_name(key)
        if child:
            if child.get_children():
                return child
            else:
                return child.get_content()
        elif self.has_attr(key):
            return self.get_attr(key)
        raise KeyError(_('No element by given name %s.') % (key))

    def __setitem__(self, key, value):
        """Dict setter method for NaElement.

           Accepts dict, list, tuple, str, int, float and long as valid value.
        """
        if key:
            if value:
                if isinstance(value, NaElement):
                    child = NaElement(key)
                    child.add_child_elem(value)
                    self.add_child_elem(child)
                elif isinstance(value, (str, int, float)):
                    self.add_new_child(key, str(value))
                elif isinstance(value, (list, tuple, dict)):
                    child = NaElement(key)
                    child.translate_struct(value)
                    self.add_child_elem(child)
                else:
                    raise TypeError(_('Not a valid value for NaElement.'))
            else:
                self.add_child_elem(NaElement(key))
        else:
            raise KeyError(_('NaElement name cannot be null.'))

    def translate_struct(self, data_struct):
        """Convert list, tuple, dict to NaElement and appends.

           Example usage:

           1.

           .. code-block:: xml

                <root>
                    <elem1>vl1</elem1>
                    <elem2>vl2</elem2>
                    <elem3>vl3</elem3>
                </root>

           The above can be achieved by doing

           .. code-block:: python

                root = NaElement('root')
                root.translate_struct({'elem1': 'vl1', 'elem2': 'vl2',
                                       'elem3': 'vl3'})

           2.

           .. code-block:: xml

                <root>
                    <elem1>vl1</elem1>
                    <elem2>vl2</elem2>
                    <elem1>vl3</elem1>
                </root>

           The above can be achieved by doing

           .. code-block:: python

                root = NaElement('root')
                root.translate_struct([{'elem1': 'vl1', 'elem2': 'vl2'},
                                       {'elem1': 'vl3'}])
        """
        if isinstance(data_struct, (list, tuple)):
            for el in data_struct:
                if isinstance(el, (list, tuple, dict)):
                    self.translate_struct(el)
                else:
                    self.add_child_elem(NaElement(el))
        elif isinstance(data_struct, dict):
            for k in data_struct.keys():
                child = NaElement(k)
                if isinstance(data_struct[k], (dict, list, tuple)):
                    child.translate_struct(data_struct[k])
                else:
                    if data_struct[k]:
                        child.set_content(str(data_struct[k]))
                self.add_child_elem(child)
        else:
            raise ValueError(_('Type cannot be converted into NaElement.'))


class NaApiError(Exception):
    """Base exception class for NetApp API errors."""

    def __init__(self, code='unknown', message='unknown'):
        self.code = code
        self.message = message

    def __str__(self, *args, **kwargs):
        return 'NetApp API failed. Reason - %s:%s' % (self.code, self.message)


class NaRetryableError(NaApiError):
    def __str__(self, *args, **kwargs):
        return 'NetApp API failed. Try again. Reason - %s:%s' % (
            self.code, self.message)


class SSHUtil(object):
    """Encapsulates connection logic and command execution for SSH client."""

    MAX_CONCURRENT_SSH_CONNECTIONS = 5
    RECV_TIMEOUT = 3
    CONNECTION_KEEP_ALIVE = 600
    WAIT_ON_STDOUT_TIMEOUT = 3

    def __init__(self, host, username, password, port=22):
        self.ssh_pool = self._init_ssh_pool(host, port, username, password)

        # Note(cfouts) Number of SSH connections made to the backend need to be
        # limited. Use of SSHPool allows connections to be cached and reused
        # instead of creating a new connection each time a command is executed
        # via SSH.
        self.ssh_connect_semaphore = semaphore.Semaphore(
            self.MAX_CONCURRENT_SSH_CONNECTIONS)

    def _init_ssh_pool(self, host, port, username, password):
        return ssh_utils.SSHPool(host,
                                 port,
                                 self.CONNECTION_KEEP_ALIVE,
                                 username,
                                 password)

    def execute_command(self, client, command_text, timeout=RECV_TIMEOUT):
        LOG.debug("execute_command() - Sending command.")
        stdin, stdout, stderr = client.exec_command(command_text)
        stdin.close()
        self._wait_on_stdout(stdout, timeout)
        output = stdout.read()
        LOG.debug("Output of length %(size)d received.",
                  {'size': len(output)})
        stdout.close()
        stderr.close()
        return output

    def execute_command_with_prompt(self,
                                    client,
                                    command,
                                    expected_prompt_text,
                                    prompt_response,
                                    timeout=RECV_TIMEOUT):
        LOG.debug("execute_command_with_prompt() - Sending command.")
        stdin, stdout, stderr = client.exec_command(command)
        self._wait_on_stdout(stdout, timeout)
        response = stdout.channel.recv(999)
        if expected_prompt_text not in response.strip().decode():
            msg = _("Unexpected output. Expected [%(expected)s] but "
                    "received [%(output)s]")\
                % {'expected': expected_prompt_text,
                   'output': response.strip(), }
            LOG.error(msg)
            stdin.close()
            stdout.close()
            stderr.close()
            raise exception.VolumeBackendAPIException(msg)
        else:
            LOG.debug("execute_command_with_prompt() - Sending answer")
            stdin.write(prompt_response + '\n')
            stdin.flush()
        stdin.close()
        stdout.close()
        stderr.close()

    def _wait_on_stdout(self, stdout, timeout=WAIT_ON_STDOUT_TIMEOUT):
        wait_time = 0.0
        # NOTE(cfouts): The server does not always indicate when EOF is reached
        # for stdout. The timeout exists for this reason and an attempt is made
        # to read from stdout.
        while not stdout.channel.exit_status_ready():
            # period is 10 - 25 centiseconds
            period = random.randint(10, 25) / 100.0
            greenthread.sleep(period)
            wait_time += period
            if wait_time > timeout:
                LOG.debug("Timeout exceeded while waiting for exit status.")
                break


# REST API error codes.
REST_UNAUTHORIZED = '6'
REST_API_NOT_FOUND = '3'
REST_UPDATE_SNAPMIRROR_FAILED = '13303844'
REST_ERELATION_EXISTS = '6619637'
REST_SNAPMIRROR_IN_PROGRESS = '13303810'
REST_UPDATE_SNAPMIRROR_FAILED = '13303844'
REST_NO_SUCH_LUN_MAP = '5374922'
REST_NO_SUCH_FILE = '6684674'
REST_NAMESPACE_EOBJECTNOTFOUND = ('72090006', '72090006')


class RestNaServer(object):
    TRANSPORT_TYPE_HTTP = 'http'
    TRANSPORT_TYPE_HTTPS = 'https'
    HTTP_PORT = '80'
    HTTPS_PORT = '443'

    TRANSPORT_PORT = {
        TRANSPORT_TYPE_HTTP: HTTP_PORT,
        TRANSPORT_TYPE_HTTPS: HTTPS_PORT
    }

    def __init__(self, host, transport_type=TRANSPORT_TYPE_HTTP,
                 ssl_cert_path=None, username=None, password=None, port=None,
                 api_trace_pattern=None,
                 private_key_file=None, certificate_file=None,
                 ca_certificate_file=None, certificate_host_validation=None):
        self._host = host
        self.set_transport_type(transport_type)
        self.set_port(port=port)
        self._username = username
        self._password = password
        self._private_key_file = private_key_file
        self._certificate_file = certificate_file
        self._ca_certificate_file = ca_certificate_file
        self._certificate_host_validation = certificate_host_validation

        if api_trace_pattern is not None:
            na_utils.setup_api_trace_pattern(api_trace_pattern)

        if ssl_cert_path is not None:
            self._ssl_verify = ssl_cert_path
        else:
            # Note(felipe_rodrigues): it will verify with the Mozila CA roots,
            # given by certifi package.
            self._ssl_verify = True

        self._api_version = None
        self._api_major_version = None
        self._api_minor_version = None
        self._ontap_version = None
        self._timeout = None

        LOG.debug('Using REST with NetApp controller: %s', self._host)

    def set_transport_type(self, transport_type):
        """Set the transport type protocol for API.

        Supports http and https transport types.
        """
        if transport_type is None or transport_type.lower() not in (
                RestNaServer.TRANSPORT_TYPE_HTTP,
                RestNaServer.TRANSPORT_TYPE_HTTPS):
            raise ValueError('Unsupported transport type')
        self._protocol = transport_type.lower()

    def get_transport_type(self):
        """Get the transport type protocol."""
        return self._protocol

    def set_api_version(self, major, minor):
        """Set the API version."""
        try:
            self._api_major_version = int(major)
            self._api_minor_version = int(minor)
            self._api_version = str(major) + "." + str(minor)
        except ValueError:
            raise ValueError('Major and minor versions must be integers')

    def get_api_version(self):
        """Gets the API version tuple."""
        if not self._api_version:
            return None
        return (self._api_major_version, self._api_minor_version)

    def set_ontap_version(self, ontap_version):
        """Set the ONTAP version."""
        self._ontap_version = ontap_version

    def get_ontap_version(self):
        """Gets the ONTAP version."""
        return self._ontap_version

    def set_port(self, port=None):
        """Set the ONTAP port, if not informed, set with default one."""
        if port is None and self._protocol in RestNaServer.TRANSPORT_PORT:
            self._port = RestNaServer.TRANSPORT_PORT[self._protocol]
        else:
            try:
                int(port)
            except ValueError:
                raise ValueError('Port must be integer')
            self._port = str(port)

    def get_port(self):
        """Get the server communication port."""
        return self._port

    def set_timeout(self, seconds):
        """Sets the timeout in seconds."""
        try:
            self._timeout = int(seconds)
        except ValueError:
            raise ValueError('timeout in seconds must be integer')

    def get_timeout(self):
        """Gets the timeout in seconds if set."""
        return self._timeout

    def set_vserver(self, vserver):
        """Set the vserver to use if tunneling gets enabled."""
        self._vserver = vserver

    def get_vserver(self):
        """Get the vserver to use in tunneling."""
        return self._vserver

    def __str__(self):
        """Gets a representation of the client."""
        return "server: %s" % (self._host)

    def _get_request_method(self, method, session):
        """Returns the request method to be used in the REST call."""

        request_methods = {
            'post': session.post,
            'get': session.get,
            'put': session.put,
            'delete': session.delete,
            'patch': session.patch,
        }
        return request_methods[method]

    def _add_query_params_to_url(self, url, query):
        """Populates the URL with specified filters."""
        filters = '&'.join([f"{k}={v}" for k, v in query.items()])
        url += "?" + filters
        return url

    def _get_base_url(self):
        """Get the base URL for REST requests."""
        host = self._host
        if ':' in host:
            host = '[%s]' % host
        return '%s://%s:%s/api/' % (self._protocol, host, self._port)

    def _build_session(self, headers):
        """Builds a session in the client."""
        self._session = requests.Session()

        # NOTE(felipe_rodrigues): request resilient of temporary network
        # failures (like name resolution failure), retrying until 5 times.
        max_retries = Retry(total=5, connect=5, read=2, backoff_factor=1)
        adapter = HTTPAdapter(max_retries=max_retries)
        self._session.mount('%s://' % self._protocol, adapter)
        if self._private_key_file and self._certificate_file:
            self._session.cert, self._session.verify\
                = self._create_certificate_auth_handler()
        else:
            self._session.auth = self._create_basic_auth_handler()
            self._session.verify = self._ssl_verify
        self._session.headers = headers

    def _build_headers(self, enable_tunneling):
        """Build and return headers for a REST request."""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        if enable_tunneling:
            headers["X-Dot-SVM-Name"] = self.get_vserver()

        return headers

    def _create_basic_auth_handler(self):
        """Creates and returns a basic HTTP auth handler."""
        return auth.HTTPBasicAuth(self._username, self._password)

    def _create_certificate_auth_handler(self):
        """Creates and returns a certificate auth handler."""
        self._certificate_host_validation = self._session.verify
        if self._certificate_file and self._private_key_file \
                and self._ca_certificate_file:
            self._session.cert = (self._certificate_file,
                                  self._private_key_file)
            if self._certificate_host_validation:
                self._session.verify = self._ca_certificate_file
        elif self._certificate_file and self._private_key_file:
            self._session.cert = (self._certificate_file,
                                  self._private_key_file)
        return self._session.cert, self._session.verify

    @volume_utils.trace_api(
        filter_function=na_utils.trace_filter_func_rest_api)
    def send_http_request(self, method, url, body, headers):
        """Invoke the API on the server.

        The passed parameters and returned parameters will be logged if trace
        feature is on. They are important for debugging purpose.
        """
        data = jsonutils.dumps(body) if body else {}

        self._build_session(headers)
        request_method = self._get_request_method(method, self._session)

        try:
            if self._timeout is not None:
                response = request_method(
                    url, data=data, timeout=self._timeout)
            else:
                response = request_method(url, data=data)
        except requests.HTTPError as e:
            raise NaApiError(e.errno, e.strerror)
        except Exception as e:
            raise NaApiError(message=e)

        code = response.status_code
        body = jsonutils.loads(response.content) if response.content else {}
        return code, body

    def invoke_successfully(self, action_url, method, body=None, query=None,
                            enable_tunneling=False):
        """Invokes REST API and checks execution status as success."""
        headers = self._build_headers(enable_tunneling)
        if query:
            action_url = self._add_query_params_to_url(action_url, query)
        url = self._get_base_url() + action_url
        code, response = self.send_http_request(method, url, body, headers)

        if not response.get('error'):
            return code, response

        result_error = response.get('error')
        code = result_error.get('code', 'ESTATUSFAILED')
        # TODO: add the correct code number for REST not licensed clone error.
        if code == ESIS_CLONE_NOT_LICENSED:
            msg = 'Clone operation failed: FlexClone not licensed.'
        else:
            msg = (result_error.get('message')
                   or 'Execution status is failed due to unknown reason')
        raise NaApiError(code, msg)
