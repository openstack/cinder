# Copyright (c) 2014 X-IO.
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

from lxml import etree
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import base64
from oslo_service import loopingcall
from six.moves import urllib

from cinder import context
from cinder import exception
from cinder import interface
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume import qos_specs
from cinder.volume import volume_types
from cinder.zonemanager import utils as fczm_utils

XIO_OPTS = [
    cfg.IntOpt('ise_storage_pool', default=1,
               help='Default storage pool for volumes.'),
    cfg.IntOpt('ise_raid', default=1,
               help='Raid level for ISE volumes.'),
    cfg.IntOpt('ise_connection_retries', default=5,
               help='Number of retries (per port) when establishing '
               'connection to ISE management port.'),
    cfg.IntOpt('ise_retry_interval', default=1,
               help='Interval (secs) between retries.'),
    cfg.IntOpt('ise_completion_retries', default=30,
               help='Number on retries to get completion status after '
               'issuing a command to ISE.'),
]


CONF = cfg.CONF
CONF.register_opts(XIO_OPTS, group=configuration.SHARED_CONF_GROUP)

LOG = logging.getLogger(__name__)

OPERATIONAL_STATUS = 'OPERATIONAL'
PREPARED_STATUS = 'PREPARED'
INVALID_STATUS = 'VALID'
NOTFOUND_STATUS = 'NOT FOUND'


# Raise exception for X-IO driver
def RaiseXIODriverException():
    raise exception.XIODriverException()


class XIOISEDriver(driver.VolumeDriver):

    VERSION = '1.1.4'

    # Version   Changes
    # 1.0.0     Base driver
    # 1.1.0     QoS, affinity, retype and thin support
    # 1.1.1     Fix retry loop (Bug 1429283)
    # 1.1.2     Fix host object deletion (Bug 1433450).
    # 1.1.3     Wait for volume/snapshot to be deleted.
    # 1.1.4     Force target_lun to be int (Bug 1549048)

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "X-IO_technologies_CI"

    # TODO(smcginnis) Remove driver in Queens if CI is not fixed
    SUPPORTED = False

    def __init__(self, *args, **kwargs):
        super(XIOISEDriver, self).__init__()
        LOG.debug("XIOISEDriver __init__ called.")
        self.configuration = kwargs.get('configuration', None)
        self.ise_primary_ip = ''
        self.ise_secondary_ip = ''
        self.newquery = 1
        self.ise_globalid = None
        self._vol_stats = {}

    def do_setup(self, context):
        LOG.debug("XIOISEDriver do_setup called.")
        self._get_ise_globalid()

    def check_for_setup_error(self):
        LOG.debug("XIOISEDriver check_for_setup_error called.")
        # The san_ip must always be set
        if self.configuration.san_ip == "":
            LOG.error("san ip must be configured!")
            RaiseXIODriverException()
        # The san_login must always be set
        if self.configuration.san_login == "":
            LOG.error("san_login must be configured!")
            RaiseXIODriverException()
        # The san_password must always be set
        if self.configuration.san_password == "":
            LOG.error("san_password must be configured!")
            RaiseXIODriverException()
        return

    def _get_version(self):
        """Return driver version."""
        return self.VERSION

    def _send_query(self):
        """Do initial query to populate ISE global id."""
        body = ''
        url = '/query'
        resp = self._connect('GET', url, body)
        status = resp['status']
        if status != 200:
            # unsuccessful - this is fatal as we need the global id
            # to build REST requests.
            LOG.error("Array query failed - No response (%d)!", status)
            RaiseXIODriverException()
        # Successfully fetched QUERY info. Parse out globalid along with
        # ipaddress for Controller 1 and Controller 2. We assign primary
        # ipaddress to use based on controller rank
        xml_tree = etree.fromstring(resp['content'])
        # first check that the ISE is running a supported FW version
        support = {}
        support['thin'] = False
        support['clones'] = False
        support['thin-clones'] = False
        self.configuration.ise_affinity = False
        self.configuration.ise_qos = False
        capabilities = xml_tree.find('capabilities')
        if capabilities is None:
            LOG.error("Array query failed. No capabilities in response!")
            RaiseXIODriverException()
        for node in capabilities:
            if node.tag != 'capability':
                continue
            capability = node
            if capability.attrib['value'] == '49003':
                self.configuration.ise_affinity = True
            elif capability.attrib['value'] == '49004':
                self.configuration.ise_qos = True
            elif capability.attrib['value'] == '49005':
                support['thin'] = True
            elif capability.attrib['value'] == '49006':
                support['clones'] = True
            elif capability.attrib['value'] == '49007':
                support['thin-clones'] = True
        # Make sure ISE support necessary features
        if not support['clones']:
            LOG.error("ISE FW version is not compatible with OpenStack!")
            RaiseXIODriverException()
        # set up thin provisioning support
        self.configuration.san_thin_provision = support['thin-clones']
        # Fill in global id, primary and secondary ip addresses
        globalid = xml_tree.find('globalid')
        if globalid is None:
            LOG.error("Array query failed. No global id in XML response!")
            RaiseXIODriverException()
        self.ise_globalid = globalid.text
        controllers = xml_tree.find('controllers')
        if controllers is None:
            LOG.error("Array query failed. No controllers in response!")
            RaiseXIODriverException()
        for node in controllers:
            if node.tag != 'controller':
                continue
            # found a controller node
            controller = node
            ipaddress = controller.find('ipaddress')
            ranktag = controller.find('rank')
            if ipaddress is None:
                continue
            # found an ipaddress tag
            # make sure rank tag is present
            if ranktag is None:
                continue
            rank = ranktag.attrib['value']
            # make sure rank value is present
            if rank is None:
                continue
            if rank == '1':
                # rank 1 means primary (xo)
                self.ise_primary_ip = ipaddress.text
                LOG.debug('Setting primary IP to: %s.',
                          self.ise_primary_ip)
            elif rank == '0':
                # rank 0 means secondary (nxo)
                self.ise_secondary_ip = ipaddress.text
                LOG.debug('Setting secondary IP to: %s.',
                          self.ise_secondary_ip)
        # clear out new query request flag on successful fetch of QUERY info.
        self.newquery = 0
        return support

    def _get_ise_globalid(self):
        """Return ISE globalid."""
        if self.ise_globalid is None or self.newquery == 1:
            # this call will populate globalid
            self._send_query()
        if self.ise_globalid is None:
            LOG.error("ISE globalid not set!")
            RaiseXIODriverException()
        return self.ise_globalid

    def _get_ise_primary_ip(self):
        """Return Primary IP address to REST API."""
        if self.ise_primary_ip == '':
            # Primary IP is set to ISE IP passed in from cinder.conf
            self.ise_primary_ip = self.configuration.san_ip
        if self.ise_primary_ip == '':
            # No IP - fatal.
            LOG.error("Primary IP must be set!")
            RaiseXIODriverException()
        return self.ise_primary_ip

    def _get_ise_secondary_ip(self):
        """Return Secondary IP address to REST API."""
        if self.ise_secondary_ip != '':
            return self.ise_secondary_ip

    def _get_uri_prefix(self):
        """Returns prefix in form of http(s)://1.2.3.4"""
        prefix = ''
        # figure out if http or https should be used
        if self.configuration.driver_use_ssl:
            prefix = 'https://'
        else:
            prefix = 'http://'
        # add the IP address
        prefix += self._get_ise_primary_ip()
        return prefix

    def _opener(self, method, url, body, header):
        """Wrapper to handle connection"""
        response = {}
        response['status'] = 0
        response['content'] = ''
        response['location'] = ''
        # send the request
        req = urllib.request.Request(url, body, header)
        # Override method to allow GET, PUT, POST, DELETE
        req.get_method = lambda: method
        try:
            # IP addr formed from code and cinder.conf so URL can be trusted
            resp = urllib.request.urlopen(req)  # nosec
        except urllib.error.HTTPError as err:
            # HTTP error. Return HTTP status and content and let caller
            # handle retries.
            response['status'] = err.code
            response['content'] = err.read()
        except urllib.error.URLError as err:
            # Connection failure.  Return a status of 0 to indicate error.
            response['status'] = 0
        else:
            # Successful. Return status code, content,
            # and location header, if present.
            response['status'] = resp.getcode()
            response['content'] = resp.read()
            response['location'] = \
                resp.info().getheader('Content-Location', '')
        return response

    def _help_call_method(self, args, retry_count):
        """Helper function used for prepare clone and delete REST calls."""
        # This function calls request method and URL and checks the response.
        # Certain cases allows for retries, while success and fatal status
        # will fall out and tell parent to break out of loop.
        # initialize remaining to one less than retries
        remaining = retry_count
        resp = self._send_cmd(args['method'], args['url'], args['arglist'])
        status = resp['status']
        if (status == 400):
            reason = ''
            if 'content' in resp:
                reason = etree.fromstring(resp['content'])
                if reason is not None:
                    reason = reason.text.upper()
            if INVALID_STATUS in reason:
                # Request failed with an invalid state. This can be because
                # source volume is in a temporary unavailable state.
                LOG.debug('REST call failed with invalid state: '
                          '%(method)s - %(status)d - %(reason)s',
                          {'method': args['method'],
                           'status': status, 'reason': reason})
                # Let parent check retry eligibility based on remaining retries
                remaining -= 1
            else:
                # Fatal error. Set remaining to 0 to make caller exit loop.
                remaining = 0
        else:
            # set remaining to 0 to make caller exit loop
            # original waiter will handle the difference between success and
            # fatal error based on resp['status'].
            remaining = 0
        return (remaining, resp)

    def _help_call_opener(self, args, retry_count):
        """Helper function to call _opener."""
        # This function calls _opener func and checks the response.
        # If response is 0 it will decrement the remaining retry count.
        # On successful connection it will set remaining to 0 to signal
        # parent to break out of loop.
        remaining = retry_count
        response = self._opener(args['method'], args['url'],
                                args['body'], args['header'])
        if response['status'] != 0:
            # We are done
            remaining = 0
        else:
            # Let parent check retry eligibility based on remaining retries.
            remaining -= 1
        # Return remaining and response
        return (remaining, response)

    def _help_wait_for_status(self, args, retry_count):
        """Helper function to wait for specified volume status"""
        # This function calls _get_volume_info and checks the response.
        # If the status strings do not match the specified status it will
        # return the remaining retry count decremented by one.
        # On successful match it will set remaining to 0 to signal
        # parent to break out of loop.
        remaining = retry_count
        info = self._get_volume_info(args['name'])
        status = args['status_string']
        if (status in info['string'] or status in info['details']):
            remaining = 0
        else:
            # Let parent check retry eligibility based on remaining retries.
            remaining -= 1
        # return remaining and volume info
        return (remaining, info)

    def _wait_for_completion(self, help_func, args, retry_count):
        """Helper function to wait for completion of passed function"""
        # Helper call loop function.
        def _call_loop(loop_args):
            remaining = loop_args['retries']
            args = loop_args['args']
            LOG.debug("In call loop (%(remaining)d) %(args)s",
                      {'remaining': remaining, 'args': args})
            (remaining, response) = loop_args['func'](args, remaining)
            if remaining == 0:
                # We are done - let our caller handle response
                raise loopingcall.LoopingCallDone(response)
            loop_args['retries'] = remaining

        # Setup retries, interval and call wait function.
        loop_args = {}
        loop_args['retries'] = retry_count
        loop_args['func'] = help_func
        loop_args['args'] = args
        interval = self.configuration.ise_retry_interval
        timer = loopingcall.FixedIntervalLoopingCall(_call_loop, loop_args)
        return timer.start(interval).wait()

    def _connect(self, method, uri, body=''):
        """Set up URL and HTML and call _opener to make request"""
        url = ''
        # see if we need to add prefix
        # this call will force primary ip to be filled in as well
        prefix = self._get_uri_prefix()
        if prefix not in uri:
            url = prefix
        url += uri
        # set up headers for XML and Auth
        header = {'Content-Type': 'application/xml; charset=utf-8'}
        auth_key = ('%s:%s'
                    % (self.configuration.san_login,
                       self.configuration.san_password))
        auth_key = base64.encode_as_text(auth_key)
        header['Authorization'] = 'Basic %s' % auth_key
        # We allow 5 retries on each IP address. If connection to primary
        # fails, secondary will be tried. If connection to secondary is
        # successful, the request flag for a new QUERY will be set. The QUERY
        # will be sent on next connection attempt to figure out which
        # controller is primary in case it has changed.
        LOG.debug("Connect: %(method)s %(url)s %(body)s",
                  {'method': method, 'url': url, 'body': body})
        using_secondary = 0
        response = {}
        response['status'] = 0
        response['location'] = ''
        response['content'] = ''
        primary_ip = self._get_ise_primary_ip()
        secondary_ip = self._get_ise_secondary_ip()
        # This will first try connecting to primary IP and then secondary IP.
        args = {}
        args['method'] = method
        args['url'] = url
        args['body'] = body
        args['header'] = header
        retries = self.configuration.ise_connection_retries
        while True:
            response = self._wait_for_completion(self._help_call_opener,
                                                 args, retries)
            if response['status'] != 0:
                # Connection succeeded. Request new query on next connection
                # attempt if we used secondary ip to sort out who should be
                # primary going forward
                self.newquery = using_secondary
                return response
            # connection failed - check if we have any retries left
            if using_secondary == 0:
                # connection on primary ip failed
                # try secondary ip
                if secondary_ip is '':
                    # if secondary is not setup yet, then assert
                    # connection on primary and secondary ip failed
                    LOG.error("Connection to %s failed and no secondary!",
                              primary_ip)
                    RaiseXIODriverException()
                # swap primary for secondary ip in URL
                url = url.replace(primary_ip, secondary_ip)
                LOG.debug('Trying secondary IP URL: %s', url)
                using_secondary = 1
                continue
            # connection failed on both IPs - break out of the loop
            break
        # connection on primary and secondary ip failed
        LOG.error("Could not connect to %(primary)s or %(secondary)s!",
                  {'primary': primary_ip, 'secondary': secondary_ip})
        RaiseXIODriverException()

    def _param_string(self, params):
        """Turn (name, value) pairs into single param string"""
        param_str = []
        for name, value in params.items():
            if value != '':
                param_str.append("%s=%s" % (name, value))
        return '&'.join(param_str)

    def _send_cmd(self, method, url, params=None):
        """Prepare HTTP request and call _connect"""
        params = params or {}
        # Add params to appropriate field based on method
        if method in ('GET', 'PUT'):
            if params:
                url += '?' + self._param_string(params)
            body = ''
        elif method == 'POST':
            body = self._param_string(params)
        else:
            # method like 'DELETE'
            body = ''
        # ISE REST API is mostly synchronous but has some asynchronous
        # streaks. Add retries to work around design of ISE REST API that
        # does not allow certain operations to be in process concurrently.
        # This is only an issue if lots of CREATE/DELETE/SNAPSHOT/CLONE ops
        # are issued in short order.
        return self._connect(method, url, body)

    def find_target_chap(self):
        """Return target CHAP settings"""
        chap = {}
        chap['chap_user'] = ''
        chap['chap_passwd'] = ''
        url = '/storage/arrays/%s/ionetworks' % (self._get_ise_globalid())
        resp = self._send_cmd('GET', url)
        status = resp['status']
        if status != 200:
            LOG.warning("IOnetworks GET failed (%d)", status)
            return chap
        # Got a good response. Parse out CHAP info.  First check if CHAP is
        # enabled and if so parse out username and password.
        root = etree.fromstring(resp['content'])
        for element in root.iter():
            if element.tag != 'chap':
                continue
            chapin = element.find('chapin')
            if chapin is None:
                continue
            if chapin.attrib['value'] != '1':
                continue
            # CHAP is enabled.  Store username / pw
            chap_user = chapin.find('username')
            if chap_user is not None:
                chap['chap_user'] = chap_user.text
            chap_passwd = chapin.find('password')
            if chap_passwd is not None:
                chap['chap_passwd'] = chap_passwd.text
            break
        return chap

    def find_target_iqn(self, iscsi_ip):
        """Find Target IQN string"""
        url = '/storage/arrays/%s/controllers' % (self._get_ise_globalid())
        resp = self._send_cmd('GET', url)
        status = resp['status']
        if status != 200:
            # Not good. Throw an exception.
            LOG.error("Controller GET failed (%d)", status)
            RaiseXIODriverException()
        # Good response.  Parse out IQN that matches iscsi_ip_address
        # passed in from cinder.conf.  IQN is 'hidden' in globalid field.
        root = etree.fromstring(resp['content'])
        for element in root.iter():
            if element.tag != 'ioport':
                continue
            ipaddrs = element.find('ipaddresses')
            if ipaddrs is None:
                continue
            for ipaddr in ipaddrs.iter():
                # Look for match with iscsi_ip_address
                if ipaddr is None or ipaddr.text != iscsi_ip:
                    continue
                endpoint = element.find('endpoint')
                if endpoint is None:
                    continue
                global_id = endpoint.find('globalid')
                if global_id is None:
                    continue
                target_iqn = global_id.text
                if target_iqn != '':
                    return target_iqn
        # Did not find a matching IQN. Upsetting.
        LOG.error("Failed to get IQN!")
        RaiseXIODriverException()

    def find_target_wwns(self):
        """Return target WWN"""
        # Let's look for WWNs
        target_wwns = []
        target = ''
        url = '/storage/arrays/%s/controllers' % (self._get_ise_globalid())
        resp = self._send_cmd('GET', url)
        status = resp['status']
        if status != 200:
            # Not good. Throw an exception.
            LOG.error("Controller GET failed (%d)", status)
            RaiseXIODriverException()
        # Good response. Parse out globalid (WWN) of endpoint that matches
        # protocol and type (array).
        controllers = etree.fromstring(resp['content'])
        for controller in controllers.iter():
            if controller.tag != 'controller':
                continue
            fcports = controller.find('fcports')
            if fcports is None:
                continue
            for fcport in fcports:
                if fcport.tag != 'fcport':
                    continue
                wwn_tag = fcport.find('wwn')
                if wwn_tag is None:
                    continue
                target = wwn_tag.text
                target_wwns.append(target)
        return target_wwns

    def _find_target_lun(self, location):
        """Return LUN for allocation specified in location string"""
        resp = self._send_cmd('GET', location)
        status = resp['status']
        if status != 200:
            # Not good. Throw an exception.
            LOG.error("Failed to get allocation information (%d)!",
                      status)
            RaiseXIODriverException()
        # Good response. Parse out LUN.
        xml_tree = etree.fromstring(resp['content'])
        allocation = xml_tree.find('allocation')
        if allocation is not None:
            luntag = allocation.find('lun')
            if luntag is not None:
                return luntag.text
        # Did not find LUN. Throw an exception.
        LOG.error("Failed to get LUN information!")
        RaiseXIODriverException()

    def _get_volume_info(self, vol_name):
        """Return status of ISE volume"""
        vol_info = {}
        vol_info['value'] = ''
        vol_info['string'] = NOTFOUND_STATUS
        vol_info['details'] = ''
        vol_info['location'] = ''
        vol_info['size'] = ''
        # Attempt to collect status value, string and details. Also pick up
        # location string from response. Location is used in REST calls
        # DELETE/SNAPSHOT/CLONE.
        # We ask for specific volume, so response should only contain one
        # volume entry.
        url = '/storage/arrays/%s/volumes' % (self._get_ise_globalid())
        resp = self._send_cmd('GET', url, {'name': vol_name})
        if resp['status'] != 200:
            LOG.warning("Could not get status for %(name)s (%(status)d).",
                        {'name': vol_name, 'status': resp['status']})
            return vol_info
        # Good response. Parse down to Volume tag in list of one.
        root = etree.fromstring(resp['content'])
        volume_node = root.find('volume')
        if volume_node is None:
            LOG.warning("No volume node in XML content.")
            return vol_info
        # Location can be found as an attribute in the volume node tag.
        vol_info['location'] = volume_node.attrib['self']
        # Find status tag
        status = volume_node.find('status')
        if status is None:
            LOG.warning("No status payload for volume %s.", vol_name)
            return vol_info
        # Fill in value and string from status tag attributes.
        vol_info['value'] = status.attrib['value']
        vol_info['string'] = status.attrib['string'].upper()
        # Detailed status has it's own list of tags.
        details = status.find('details')
        if details is not None:
            detail = details.find('detail')
            if detail is not None:
                vol_info['details'] = detail.text.upper()
        # Get volume size
        size_tag = volume_node.find('size')
        if size_tag is not None:
            vol_info['size'] = size_tag.text
        # Return value, string, details and location.
        return vol_info

    def _alloc_location(self, volume, hostname, delete=0):
        """Find location string for allocation. Also delete alloc per reqst"""
        location = ''
        url = '/storage/arrays/%s/allocations' % (self._get_ise_globalid())
        resp = self._send_cmd('GET', url, {'name': volume['name'],
                                           'hostname': hostname})
        if resp['status'] != 200:
            LOG.error("Could not GET allocation information (%d)!",
                      resp['status'])
            RaiseXIODriverException()
        # Good response. Find the allocation based on volume name.
        allocation_tree = etree.fromstring(resp['content'])
        for allocation in allocation_tree.iter():
            if allocation.tag != 'allocation':
                continue
            # verify volume name match
            volume_tag = allocation.find('volume')
            if volume_tag is None:
                continue
            volumename_tag = volume_tag.find('volumename')
            if volumename_tag is None:
                continue
            volumename = volumename_tag.text
            if volumename != volume['name']:
                continue
            # verified volume name match
            # find endpoints list
            endpoints = allocation.find('endpoints')
            if endpoints is None:
                continue
            # Found endpoints list. Found matching host if hostname specified,
            # otherwise any host is a go.  This is used by the caller to
            # delete all allocations (presentations) to a volume.
            for endpoint in endpoints.iter():
                if hostname != '':
                    hname_tag = endpoint.find('hostname')
                    if hname_tag is None:
                        continue
                    if hname_tag.text.upper() != hostname.upper():
                        continue
                # Found hostname match. Location string is an attribute in
                # allocation tag.
                location = allocation.attrib['self']
                # Delete allocation if requested.
                if delete == 1:
                    self._send_cmd('DELETE', location)
                    location = ''
                    break
                else:
                    return location
        return location

    def _present_volume(self, volume, hostname, lun):
        """Present volume to host at specified LUN"""
        # Set up params with volume name, host name and target lun, if
        # specified.
        target_lun = lun
        params = {'volumename': volume['name'],
                  'hostname': hostname}
        # Fill in LUN if specified.
        if target_lun != '':
            params['lun'] = target_lun
        # Issue POST call to allocation.
        url = '/storage/arrays/%s/allocations' % (self._get_ise_globalid())
        resp = self._send_cmd('POST', url, params)
        status = resp['status']
        if status == 201:
            LOG.info("Volume %s presented.", volume['name'])
        elif status == 409:
            LOG.warning("Volume %(name)s already presented (%(status)d)!",
                        {'name': volume['name'], 'status': status})
        else:
            LOG.error("Failed to present volume %(name)s (%(status)d)!",
                      {'name': volume['name'], 'status': status})
            RaiseXIODriverException()
        # Fetch LUN. In theory the LUN should be what caller requested.
        # We try to use shortcut as location comes back in Location header.
        # Make sure shortcut of using location header worked, if not ask
        # for it explicitly.
        location = resp['location']
        if location == '':
            location = self._alloc_location(volume, hostname)
        # Find target LUN
        if location != '':
            target_lun = self._find_target_lun(location)
        # Success. Return target LUN.
        LOG.debug("Volume %(volume)s presented: %(host)s %(lun)s",
                  {'volume': volume['name'], 'host': hostname,
                   'lun': target_lun})
        return target_lun

    def find_allocations(self, hostname):
        """Find allocations for specified host"""
        alloc_cnt = 0
        url = '/storage/arrays/%s/allocations' % (self._get_ise_globalid())
        resp = self._send_cmd('GET', url, {'hostname': hostname})
        status = resp['status']
        if status != 200:
            LOG.error("Failed to get allocation information: "
                      "%(host)s (%(status)d)!",
                      {'host': hostname, 'status': status})
            RaiseXIODriverException()
        # Good response. Count the number of allocations.
        allocation_tree = etree.fromstring(resp['content'])
        for allocation in allocation_tree.iter():
            if allocation.tag != 'allocation':
                continue
            alloc_cnt += 1
        return alloc_cnt

    def _find_host(self, endpoints):
        """Check if host entry exists on ISE based on endpoint (IQN, WWNs)"""
        # FC host might have more than one endpoint. ISCSI has only one.
        # Check if endpoints is a list, if so use first entry in list for
        # host search.
        if type(endpoints) is list:
            for endpoint in endpoints:
                ep = endpoint
                break
        else:
            ep = endpoints
        # Got single end point. Now make REST API call to fetch all hosts
        LOG.debug("find_host: Looking for host %s.", ep)
        host = {}
        host['name'] = ''
        host['type'] = ''
        host['locator'] = ''
        params = {}
        url = '/storage/arrays/%s/hosts' % (self._get_ise_globalid())
        resp = self._send_cmd('GET', url, params)
        status = resp['status']
        if resp['status'] != 200:
            LOG.error("Could not find any hosts (%s)", status)
            RaiseXIODriverException()
        # Good response. Try to match up a host based on end point string.
        host_tree = etree.fromstring(resp['content'])
        for host_node in host_tree.iter():
            if host_node.tag != 'host':
                continue
            # Found a host tag. Check if end point matches.
            endpoints_node = host_node.find('endpoints')
            if endpoints_node is None:
                continue
            for endpoint_node in endpoints_node.iter():
                if endpoint_node.tag != 'endpoint':
                    continue
                gid = endpoint_node.find('globalid')
                if gid is None:
                    continue
                if gid.text.upper() != ep.upper():
                    continue
                # We have a match. Fill in host name, type and locator
                host['locator'] = host_node.attrib['self']
                type_tag = host_node.find('type')
                if type_tag is not None:
                    host['type'] = type_tag.text
                name_tag = host_node.find('name')
                if name_tag is not None:
                    host['name'] = name_tag.text
                break
        # This will be filled in or '' based on findings above.
        return host

    def _create_host(self, hostname, endpoints):
        """Create host entry on ISE for connector"""
        # Create endpoint list for REST call.
        endpoint_str = ''
        if type(endpoints) is list:
            ep_str = []
            ec = 0
            for endpoint in endpoints:
                if ec == 0:
                    ep_str.append("%s" % (endpoint))
                else:
                    ep_str.append("endpoint=%s" % (endpoint))
                ec += 1
            endpoint_str = '&'.join(ep_str)
        else:
            endpoint_str = endpoints
        # Log host creation.
        LOG.debug("Create host %(host)s; %(endpoint)s",
                  {'host': hostname, 'endpoint': endpoint_str})
        # Issue REST call to create host entry of OpenStack type.
        params = {'name': hostname, 'endpoint': endpoint_str,
                  'os': 'openstack'}
        url = '/storage/arrays/%s/hosts' % (self._get_ise_globalid())
        resp = self._send_cmd('POST', url, params)
        status = resp['status']
        if status != 201 and status != 409:
            LOG.error("POST for host create failed (%s)!", status)
            RaiseXIODriverException()
        # Successfully created host entry. Return host name.
        return hostname

    def _create_clone(self, volume, clone, clone_type):
        """Create clone worker function"""
        # This function is called for both snapshot and clone
        # clone_type specifies what type is being processed
        # Creating snapshots and clones is a two step process on current ISE
        # FW. First snapshot/clone is prepared and then created.
        volume_name = ''
        if clone_type == 'snapshot':
            volume_name = volume['volume_name']
        elif clone_type == 'clone':
            volume_name = volume['name']
        args = {}
        # Make sure source volume is ready. This is another case where
        # we have to work around asynchronous behavior in ISE REST API.
        args['name'] = volume_name
        args['status_string'] = OPERATIONAL_STATUS
        retries = self.configuration.ise_completion_retries
        vol_info = self._wait_for_completion(self._help_wait_for_status,
                                             args, retries)
        if vol_info['value'] == '0':
            LOG.debug('Source volume %s ready.', volume_name)
        else:
            LOG.error("Source volume %s not ready!", volume_name)
            RaiseXIODriverException()
        # Prepare snapshot
        # get extra_specs and qos specs from source volume
        # these functions fill in default values for entries used below
        ctxt = context.get_admin_context()
        type_id = volume['volume_type_id']
        extra_specs = self._get_extra_specs(ctxt, type_id)
        LOG.debug("Volume %(volume_name)s extra_specs %(extra_specs)s",
                  {'volume_name': volume['name'], 'extra_specs': extra_specs})
        qos = self._get_qos_specs(ctxt, type_id)
        # Wait until snapshot/clone is prepared.
        args['method'] = 'POST'
        args['url'] = vol_info['location']
        args['status'] = 202
        args['arglist'] = {'name': clone['name'],
                           'type': clone_type,
                           'affinity': extra_specs['affinity'],
                           'IOPSmin': qos['minIOPS'],
                           'IOPSmax': qos['maxIOPS'],
                           'IOPSburst': qos['burstIOPS']}
        retries = self.configuration.ise_completion_retries
        resp = self._wait_for_completion(self._help_call_method,
                                         args, retries)
        if resp['status'] != 202:
            # clone prepare failed - bummer
            LOG.error("Prepare clone failed for %s.", clone['name'])
            RaiseXIODriverException()
        # clone prepare request accepted
        # make sure not to continue until clone prepared
        args['name'] = clone['name']
        args['status_string'] = PREPARED_STATUS
        retries = self.configuration.ise_completion_retries
        clone_info = self._wait_for_completion(self._help_wait_for_status,
                                               args, retries)
        if PREPARED_STATUS in clone_info['details']:
            LOG.debug('Clone %s prepared.', clone['name'])
        else:
            LOG.error("Clone %s not in prepared state!", clone['name'])
            RaiseXIODriverException()
        # Clone prepared, now commit the create
        resp = self._send_cmd('PUT', clone_info['location'],
                              {clone_type: 'true'})
        if resp['status'] != 201:
            LOG.error("Commit clone failed: %(name)s (%(status)d)!",
                      {'name': clone['name'], 'status': resp['status']})
            RaiseXIODriverException()
        # Clone create request accepted. Make sure not to return until clone
        # operational.
        args['name'] = clone['name']
        args['status_string'] = OPERATIONAL_STATUS
        retries = self.configuration.ise_completion_retries
        clone_info = self._wait_for_completion(self._help_wait_for_status,
                                               args, retries)
        if OPERATIONAL_STATUS in clone_info['string']:
            LOG.info("Clone %s created.", clone['name'])
        else:
            LOG.error("Commit failed for %s!", clone['name'])
            RaiseXIODriverException()
        return

    def _fill_in_available_capacity(self, node, pool):
        """Fill in free capacity info for pool."""
        available = node.find('available')
        if available is None:
            pool['free_capacity_gb'] = 0
            return pool
        pool['free_capacity_gb'] = int(available.get('total'))
        # Fill in separate RAID level cap
        byred = available.find('byredundancy')
        if byred is None:
            return pool
        raid = byred.find('raid-0')
        if raid is not None:
            pool['free_capacity_gb_raid_0'] = int(raid.text)
        raid = byred.find('raid-1')
        if raid is not None:
            pool['free_capacity_gb_raid_1'] = int(raid.text)
        raid = byred.find('raid-5')
        if raid is not None:
            pool['free_capacity_gb_raid_5'] = int(raid.text)
        raid = byred.find('raid-6')
        if raid is not None:
            pool['free_capacity_gb_raid_6'] = int(raid.text)
        return pool

    def _fill_in_used_capacity(self, node, pool):
        """Fill in used capacity info for pool."""
        used = node.find('used')
        if used is None:
            pool['allocated_capacity_gb'] = 0
            return pool
        pool['allocated_capacity_gb'] = int(used.get('total'))
        # Fill in separate RAID level cap
        byred = used.find('byredundancy')
        if byred is None:
            return pool
        raid = byred.find('raid-0')
        if raid is not None:
            pool['allocated_capacity_gb_raid_0'] = int(raid.text)
        raid = byred.find('raid-1')
        if raid is not None:
            pool['allocated_capacity_gb_raid_1'] = int(raid.text)
        raid = byred.find('raid-5')
        if raid is not None:
            pool['allocated_capacity_gb_raid_5'] = int(raid.text)
        raid = byred.find('raid-6')
        if raid is not None:
            pool['allocated_capacity_gb_raid_6'] = int(raid.text)
        return pool

    def _get_pools(self):
        """Return information about all pools on ISE"""
        pools = []
        pool = {}
        vol_cnt = 0
        url = '/storage/pools'
        resp = self._send_cmd('GET', url)
        status = resp['status']
        if status != 200:
            # Request failed. Return what we have, which isn't much.
            LOG.warning("Could not get pool information (%s)!", status)
            return (pools, vol_cnt)
        # Parse out available (free) and used. Add them up to get total.
        xml_tree = etree.fromstring(resp['content'])
        for child in xml_tree:
            if child.tag != 'pool':
                continue
            # Fill in ise pool name
            tag = child.find('name')
            if tag is not None:
                pool['pool_ise_name'] = tag.text
            # Fill in globalid
            tag = child.find('globalid')
            if tag is not None:
                pool['globalid'] = tag.text
            # Fill in pool name
            tag = child.find('id')
            if tag is not None:
                pool['pool_name'] = tag.text
            # Fill in pool status
            tag = child.find('status')
            if tag is not None:
                pool['status'] = tag.attrib['string']
                details = tag.find('details')
                if details is not None:
                    detail = details.find('detail')
                    if detail is not None:
                        pool['status_details'] = detail.text
            # Fill in available capacity
            pool = self._fill_in_available_capacity(child, pool)
            # Fill in allocated capacity
            pool = self._fill_in_used_capacity(child, pool)
            # Fill in media health and type
            media = child.find('media')
            if media is not None:
                medium = media.find('medium')
                if medium is not None:
                    health = medium.find('health')
                    if health is not None:
                        pool['health'] = int(health.text)
                    tier = medium.find('tier')
                    if tier is not None:
                        pool['media'] = tier.attrib['string']
            cap = child.find('IOPSmincap')
            if cap is not None:
                pool['minIOPS_capacity'] = cap.text
            cap = child.find('IOPSmaxcap')
            if cap is not None:
                pool['maxIOPS_capacity'] = cap.text
            cap = child.find('IOPSburstcap')
            if cap is not None:
                pool['burstIOPS_capacity'] = cap.text
            pool['total_capacity_gb'] = (int(pool['free_capacity_gb'] +
                                             pool['allocated_capacity_gb']))
            pool['QoS_support'] = self.configuration.ise_qos
            pool['reserved_percentage'] = 0
            pools.append(pool)
            # count volumes
            volumes = child.find('volumes')
            if volumes is not None:
                vol_cnt += len(volumes)
        return (pools, vol_cnt)

    def _update_volume_stats(self):
        """Update storage information"""
        self._send_query()
        data = {}
        data["vendor_name"] = 'X-IO'
        data["driver_version"] = self._get_version()
        if self.configuration.volume_backend_name:
            backend_name = self.configuration.volume_backend_name
        else:
            backend_name = self.__class__.__name__
        data["volume_backend_name"] = backend_name
        data['reserved_percentage'] = 0
        # Get total and free capacity.
        (pools, vol_cnt) = self._get_pools()
        total_cap = 0
        free_cap = 0
        # fill in global capability support
        # capacity
        for pool in pools:
            total_cap += int(pool['total_capacity_gb'])
            free_cap += int(pool['free_capacity_gb'])
        data['total_capacity_gb'] = int(total_cap)
        data['free_capacity_gb'] = int(free_cap)
        # QoS
        data['QoS_support'] = self.configuration.ise_qos
        # Volume affinity
        data['affinity'] = self.configuration.ise_affinity
        # Thin provisioning
        data['thin'] = self.configuration.san_thin_provision
        data['pools'] = pools
        data['active_volumes'] = int(vol_cnt)
        return data

    def get_volume_stats(self, refresh=False):
        """Get volume stats."""
        if refresh:
            self._vol_stats = self._update_volume_stats()
        LOG.debug("ISE get_volume_stats (total, free): %(total)s, %(free)s",
                  {'total': self._vol_stats['total_capacity_gb'],
                   'free': self._vol_stats['free_capacity_gb']})
        return self._vol_stats

    def _get_extra_specs(self, ctxt, type_id):
        """Get extra specs from volume type."""
        specs = {}
        specs['affinity'] = ''
        specs['alloctype'] = ''
        specs['pool'] = self.configuration.ise_storage_pool
        specs['raid'] = self.configuration.ise_raid
        if type_id is not None:
            volume_type = volume_types.get_volume_type(ctxt, type_id)
            extra_specs = volume_type.get('extra_specs')
            # Parse out RAID, pool and affinity values
            for key, value in extra_specs.items():
                subkey = ''
                if ':' in key:
                    fields = key.split(':')
                    key = fields[0]
                    subkey = fields[1]
                if key.upper() == 'Feature'.upper():
                    if subkey.upper() == 'Raid'.upper():
                        specs['raid'] = value
                    elif subkey.upper() == 'Pool'.upper():
                        specs['pool'] = value
                elif key.upper() == 'Affinity'.upper():
                    # Only fill this in if ISE FW supports volume affinity
                    if self.configuration.ise_affinity:
                        if subkey.upper() == 'Type'.upper():
                            specs['affinity'] = value
                elif key.upper() == 'Alloc'.upper():
                    # Only fill this in if ISE FW supports thin provisioning
                    if self.configuration.san_thin_provision:
                        if subkey.upper() == 'Type'.upper():
                            specs['alloctype'] = value
        return specs

    def _get_qos_specs(self, ctxt, type_id):
        """Get QoS specs from volume type."""
        specs = {}
        specs['minIOPS'] = ''
        specs['maxIOPS'] = ''
        specs['burstIOPS'] = ''
        if type_id is not None:
            volume_type = volume_types.get_volume_type(ctxt, type_id)
            qos_specs_id = volume_type.get('qos_specs_id')
            if qos_specs_id is not None:
                kvs = qos_specs.get_qos_specs(ctxt, qos_specs_id)['specs']
            else:
                kvs = volume_type.get('extra_specs')
            # Parse out min, max and burst values
            for key, value in kvs.items():
                if ':' in key:
                    fields = key.split(':')
                    key = fields[1]
                if key.upper() == 'minIOPS'.upper():
                    specs['minIOPS'] = value
                elif key.upper() == 'maxIOPS'.upper():
                    specs['maxIOPS'] = value
                elif key.upper() == 'burstIOPS'.upper():
                    specs['burstIOPS'] = value
        return specs

    def create_volume(self, volume):
        """Create requested volume"""
        LOG.debug("X-IO create_volume called.")
        # get extra_specs and qos based on volume type
        # these functions fill in default values for entries used below
        ctxt = context.get_admin_context()
        type_id = volume['volume_type_id']
        extra_specs = self._get_extra_specs(ctxt, type_id)
        LOG.debug("Volume %(volume_name)s extra_specs %(extra_specs)s",
                  {'volume_name': volume['name'], 'extra_specs': extra_specs})
        qos = self._get_qos_specs(ctxt, type_id)
        # Make create call
        url = '/storage/arrays/%s/volumes' % (self._get_ise_globalid())
        resp = self._send_cmd('POST', url,
                              {'name': volume['name'],
                               'size': volume['size'],
                               'pool': extra_specs['pool'],
                               'redundancy': extra_specs['raid'],
                               'affinity': extra_specs['affinity'],
                               'alloctype': extra_specs['alloctype'],
                               'IOPSmin': qos['minIOPS'],
                               'IOPSmax': qos['maxIOPS'],
                               'IOPSburst': qos['burstIOPS']})
        if resp['status'] != 201:
            LOG.error("Failed to create volume: %(name)s (%(status)s)",
                      {'name': volume['name'], 'status': resp['status']})
            RaiseXIODriverException()
        # Good response. Make sure volume is in operational state before
        # returning. Volume creation completes asynchronously.
        args = {}
        args['name'] = volume['name']
        args['status_string'] = OPERATIONAL_STATUS
        retries = self.configuration.ise_completion_retries
        vol_info = self._wait_for_completion(self._help_wait_for_status,
                                             args, retries)
        if OPERATIONAL_STATUS in vol_info['string']:
            # Ready.
            LOG.info("Volume %s created", volume['name'])
        else:
            LOG.error("Failed to create volume %s.", volume['name'])
            RaiseXIODriverException()
        return

    def create_cloned_volume(self, volume, src_vref):
        """Create clone"""
        LOG.debug("X-IO create_cloned_volume called.")
        self._create_clone(src_vref, volume, 'clone')

    def create_snapshot(self, snapshot):
        """Create snapshot"""
        LOG.debug("X-IO create_snapshot called.")
        # Creating a snapshot uses same interface as clone operation on
        # ISE. Clone type ('snapshot' or 'clone') tells the ISE what kind
        # of operation is requested.
        self._create_clone(snapshot, snapshot, 'snapshot')

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create volume from snapshot"""
        LOG.debug("X-IO create_volume_from_snapshot called.")
        # ISE snapshots are just like a volume so this is a clone operation.
        self._create_clone(snapshot, volume, 'clone')

    def _delete_volume(self, volume):
        """Delete specified volume"""
        # First unpresent volume from all hosts.
        self._alloc_location(volume, '', 1)
        # Get volume status. Location string for volume comes back
        # in response. Used for DELETE call below.
        vol_info = self._get_volume_info(volume['name'])
        if vol_info['location'] == '':
            LOG.warning("%s not found!", volume['name'])
            return
        # Make DELETE call.
        args = {}
        args['method'] = 'DELETE'
        args['url'] = vol_info['location']
        args['arglist'] = {}
        args['status'] = 204
        retries = self.configuration.ise_completion_retries
        resp = self._wait_for_completion(self._help_call_method, args, retries)
        if resp['status'] != 204:
            LOG.warning("DELETE call failed for %s!", volume['name'])
            return
        # DELETE call successful, now wait for completion.
        # We do that by waiting for the REST call to return Volume Not Found.
        args['method'] = ''
        args['url'] = ''
        args['name'] = volume['name']
        args['status_string'] = NOTFOUND_STATUS
        retries = self.configuration.ise_completion_retries
        vol_info = self._wait_for_completion(self._help_wait_for_status,
                                             args, retries)
        if NOTFOUND_STATUS in vol_info['string']:
            # Volume no longer present on the backend.
            LOG.info("Successfully deleted %s.", volume['name'])
            return
        # If we come here it means the volume is still present
        # on the backend.
        LOG.error("Timed out deleting %s!", volume['name'])
        return

    def delete_volume(self, volume):
        """Delete specified volume"""
        LOG.debug("X-IO delete_volume called.")
        self._delete_volume(volume)

    def delete_snapshot(self, snapshot):
        """Delete snapshot"""
        LOG.debug("X-IO delete_snapshot called.")
        # Delete snapshot and delete volume is identical to ISE.
        self._delete_volume(snapshot)

    def _modify_volume(self, volume, new_attributes):
        # Get volume status. Location string for volume comes back
        # in response. Used for PUT call below.
        vol_info = self._get_volume_info(volume['name'])
        if vol_info['location'] == '':
            LOG.error("modify volume: %s does not exist!", volume['name'])
            RaiseXIODriverException()
        # Make modify volume REST call using PUT.
        # Location from above is used as identifier.
        resp = self._send_cmd('PUT', vol_info['location'], new_attributes)
        status = resp['status']
        if status == 201:
            LOG.debug("Volume %s modified.", volume['name'])
            return True
        LOG.error("Modify volume PUT failed: %(name)s (%(status)d).",
                  {'name': volume['name'], 'status': status})
        RaiseXIODriverException()

    def extend_volume(self, volume, new_size):
        """Extend volume to new size."""
        LOG.debug("extend_volume called")
        ret = self._modify_volume(volume, {'size': new_size})
        if ret is True:
            LOG.info("volume %(name)s extended to %(size)d.",
                     {'name': volume['name'], 'size': new_size})
        return

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""
        LOG.debug("X-IO retype called")
        qos = self._get_qos_specs(ctxt, new_type['id'])
        ret = self._modify_volume(volume, {'IOPSmin': qos['minIOPS'],
                                           'IOPSmax': qos['maxIOPS'],
                                           'IOPSburst': qos['burstIOPS']})
        if ret is True:
            LOG.info("Volume %s retyped.", volume['name'])
        return True

    def manage_existing(self, volume, ise_volume_ref):
        """Convert an existing ISE volume to a Cinder volume."""
        LOG.debug("X-IO manage_existing called")
        if 'source-name' not in ise_volume_ref:
            LOG.error("manage_existing: No source-name in ref!")
            RaiseXIODriverException()
        # copy the source-name to 'name' for modify volume use
        ise_volume_ref['name'] = ise_volume_ref['source-name']
        ctxt = context.get_admin_context()
        qos = self._get_qos_specs(ctxt, volume['volume_type_id'])
        ret = self._modify_volume(ise_volume_ref,
                                  {'name': volume['name'],
                                   'IOPSmin': qos['minIOPS'],
                                   'IOPSmax': qos['maxIOPS'],
                                   'IOPSburst': qos['burstIOPS']})
        if ret is True:
            LOG.info("Volume %s converted.", ise_volume_ref['name'])
        return ret

    def manage_existing_get_size(self, volume, ise_volume_ref):
        """Get size of an existing ISE volume."""
        LOG.debug("X-IO manage_existing_get_size called")
        if 'source-name' not in ise_volume_ref:
            LOG.error("manage_existing_get_size: No source-name in ref!")
            RaiseXIODriverException()
        ref_name = ise_volume_ref['source-name']
        # get volume status including size
        vol_info = self._get_volume_info(ref_name)
        if vol_info['location'] == '':
            LOG.error("manage_existing_get_size: %s does not exist!",
                      ref_name)
            RaiseXIODriverException()
        return int(vol_info['size'])

    def unmanage(self, volume):
        """Remove Cinder management from ISE volume"""
        LOG.debug("X-IO unmanage called")
        vol_info = self._get_volume_info(volume['name'])
        if vol_info['location'] == '':
            LOG.error("unmanage: Volume %s does not exist!",
                      volume['name'])
            RaiseXIODriverException()
        # This is a noop. ISE does not store any Cinder specific information.

    def ise_present(self, volume, hostname_in, endpoints):
        """Set up presentation for volume and specified connector"""
        LOG.debug("X-IO ise_present called.")
        # Create host entry on ISE if necessary.
        # Check to see if host entry already exists.
        # Create if not found
        host = self._find_host(endpoints)
        if host['name'] == '':
            # host not found, so create new host entry
            # Use host name if filled in. If blank, ISE will make up a name.
            self._create_host(hostname_in, endpoints)
            host = self._find_host(endpoints)
            if host['name'] == '':
                # host still not found, this is fatal.
                LOG.error("Host could not be found!")
                RaiseXIODriverException()
        elif host['type'].upper() != 'OPENSTACK':
            # Make sure host type is marked as OpenStack host
            params = {'os': 'openstack'}
            resp = self._send_cmd('PUT', host['locator'], params)
            status = resp['status']
            if status != 201 and status != 409:
                LOG.error("Host PUT failed (%s).", status)
                RaiseXIODriverException()
        # We have a host object.
        target_lun = ''
        # Present volume to host.
        target_lun = self._present_volume(volume, host['name'], target_lun)
        # Fill in target information.
        data = {}
        data['target_lun'] = int(target_lun)
        data['volume_id'] = volume['id']
        return data

    def ise_unpresent(self, volume, endpoints):
        """Delete presentation between volume and connector"""
        LOG.debug("X-IO ise_unpresent called.")
        # Delete allocation uses host name. Go find it based on endpoints.
        host = self._find_host(endpoints)
        if host['name'] != '':
            # Delete allocation based on hostname and volume.
            self._alloc_location(volume, host['name'], 1)
        return host['name']

    def create_export(self, context, volume):
        LOG.debug("X-IO create_export called.")

    def ensure_export(self, context, volume):
        LOG.debug("X-IO ensure_export called.")

    def remove_export(self, context, volume):
        LOG.debug("X-IO remove_export called.")

    def local_path(self, volume):
        LOG.debug("X-IO local_path called.")

    def delete_host(self, endpoints):
        """Delete ISE host object"""
        host = self._find_host(endpoints)
        if host['locator'] != '':
            # Delete host
            self._send_cmd('DELETE', host['locator'])
            LOG.debug("X-IO: host %s deleted", host['name'])


# Protocol specific classes for entry.  They are wrappers around base class
# above and every external API resuslts in a call to common function in base
# class.
@interface.volumedriver
class XIOISEISCSIDriver(driver.ISCSIDriver):

    """Requires ISE Running FW version 3.1.0 or higher"""

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = 'X-IO_technologies_CI'
    VERSION = XIOISEDriver.VERSION

    def __init__(self, *args, **kwargs):
        super(XIOISEISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(XIO_OPTS)
        self.configuration.append_config_values(san.san_opts)

        # The iscsi_ip_address must always be set.
        if self.configuration.iscsi_ip_address == '':
            LOG.error("iscsi_ip_address must be set!")
            RaiseXIODriverException()
        # Setup common driver
        self.driver = XIOISEDriver(configuration=self.configuration)

    def do_setup(self, context):
        return self.driver.do_setup(context)

    def check_for_setup_error(self):
        return self.driver.check_for_setup_error()

    def local_path(self, volume):
        return self.driver.local_path(volume)

    def get_volume_stats(self, refresh=False):
        data = self.driver.get_volume_stats(refresh)
        data["storage_protocol"] = 'iSCSI'
        return data

    def create_volume(self, volume):
        self.driver.create_volume(volume)
        # Volume created successfully. Fill in CHAP information.
        model_update = {}
        chap = self.driver.find_target_chap()
        if chap['chap_user'] != '':
            model_update['provider_auth'] = 'CHAP %s %s' % \
                (chap['chap_user'], chap['chap_passwd'])
        else:
            model_update['provider_auth'] = ''
        return model_update

    def create_cloned_volume(self, volume, src_vref):
        return self.driver.create_cloned_volume(volume, src_vref)

    def create_volume_from_snapshot(self, volume, snapshot):
        return self.driver.create_volume_from_snapshot(volume, snapshot)

    def delete_volume(self, volume):
        return self.driver.delete_volume(volume)

    def extend_volume(self, volume, new_size):
        return self.driver.extend_volume(volume, new_size)

    def retype(self, ctxt, volume, new_type, diff, host):
        return self.driver.retype(ctxt, volume, new_type, diff, host)

    def manage_existing(self, volume, ise_volume_ref):
        ret = self.driver.manage_existing(volume, ise_volume_ref)
        if ret is True:
            # Volume converted successfully. Fill in CHAP information.
            model_update = {}
            chap = {}
            chap = self.driver.find_target_chap()
            if chap['chap_user'] != '':
                model_update['provider_auth'] = 'CHAP %s %s' % \
                    (chap['chap_user'], chap['chap_passwd'])
            else:
                model_update['provider_auth'] = ''
            return model_update

    def manage_existing_get_size(self, volume, ise_volume_ref):
        return self.driver.manage_existing_get_size(volume, ise_volume_ref)

    def unmanage(self, volume):
        return self.driver.unmanage(volume)

    def initialize_connection(self, volume, connector):
        hostname = ''
        if 'host' in connector:
            hostname = connector['host']
        data = self.driver.ise_present(volume, hostname,
                                       connector['initiator'])
        # find IP for target
        data['target_portal'] = \
            '%s:3260' % (self.configuration.iscsi_ip_address)
        # set IQN for target
        data['target_discovered'] = False
        data['target_iqn'] = \
            self.driver.find_target_iqn(self.configuration.iscsi_ip_address)
        # Fill in authentication method (CHAP)
        if 'provider_auth' in volume:
            auth = volume['provider_auth']
            if auth:
                (auth_method, auth_username, auth_secret) = auth.split()
                data['auth_method'] = auth_method
                data['auth_username'] = auth_username
                data['auth_password'] = auth_secret
        return {'driver_volume_type': 'iscsi',
                'data': data}

    def terminate_connection(self, volume, connector, **kwargs):
        hostname = self.driver.ise_unpresent(volume, connector['initiator'])
        alloc_cnt = 0
        if hostname != '':
            alloc_cnt = self.driver.find_allocations(hostname)
            if alloc_cnt == 0:
                # delete host object
                self.driver.delete_host(connector['initiator'])

    def create_snapshot(self, snapshot):
        return self.driver.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        return self.driver.delete_snapshot(snapshot)

    def create_export(self, context, volume, connector):
        return self.driver.create_export(context, volume)

    def ensure_export(self, context, volume):
        return self.driver.ensure_export(context, volume)

    def remove_export(self, context, volume):
        return self.driver.remove_export(context, volume)


@interface.volumedriver
class XIOISEFCDriver(driver.FibreChannelDriver):

    """Requires ISE Running FW version 2.8.0 or higher"""

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = 'X-IO_technologies_CI'
    VERSION = XIOISEDriver.VERSION

    def __init__(self, *args, **kwargs):
        super(XIOISEFCDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(XIO_OPTS)
        self.configuration.append_config_values(san.san_opts)
        self.driver = XIOISEDriver(configuration=self.configuration)

    def do_setup(self, context):
        return self.driver.do_setup(context)

    def check_for_setup_error(self):
        return self.driver.check_for_setup_error()

    def local_path(self, volume):
        return self.driver.local_path(volume)

    def get_volume_stats(self, refresh=False):
        data = self.driver.get_volume_stats(refresh)
        data["storage_protocol"] = 'fibre_channel'
        return data

    def create_volume(self, volume):
        return self.driver.create_volume(volume)

    def create_cloned_volume(self, volume, src_vref):
        return self.driver.create_cloned_volume(volume, src_vref)

    def create_volume_from_snapshot(self, volume, snapshot):
        return self.driver.create_volume_from_snapshot(volume, snapshot)

    def delete_volume(self, volume):
        return self.driver.delete_volume(volume)

    def extend_volume(self, volume, new_size):
        return self.driver.extend_volume(volume, new_size)

    def retype(self, ctxt, volume, new_type, diff, host):
        return self.driver.retype(ctxt, volume, new_type, diff, host)

    def manage_existing(self, volume, ise_volume_ref):
        return self.driver.manage_existing(volume, ise_volume_ref)

    def manage_existing_get_size(self, volume, ise_volume_ref):
        return self.driver.manage_existing_get_size(volume, ise_volume_ref)

    def unmanage(self, volume):
        return self.driver.unmanage(volume)

    @fczm_utils.add_fc_zone
    def initialize_connection(self, volume, connector):
        hostname = ''
        if 'host' in connector:
            hostname = connector['host']
        data = self.driver.ise_present(volume, hostname, connector['wwpns'])
        data['target_discovered'] = True
        # set wwns for target
        target_wwns = self.driver.find_target_wwns()
        data['target_wwn'] = target_wwns
        # build target initiator map
        target_map = {}
        for initiator in connector['wwpns']:
            target_map[initiator] = target_wwns
        data['initiator_target_map'] = target_map
        return {'driver_volume_type': 'fibre_channel',
                'data': data}

    @fczm_utils.remove_fc_zone
    def terminate_connection(self, volume, connector, **kwargs):
        # now we are ready to tell ISE to delete presentations
        hostname = self.driver.ise_unpresent(volume, connector['wwpns'])
        # set target_wwn and initiator_target_map only if host
        # has no more presentations
        data = {}
        alloc_cnt = 0
        if hostname != '':
            alloc_cnt = self.driver.find_allocations(hostname)
            if alloc_cnt == 0:
                target_wwns = self.driver.find_target_wwns()
                data['target_wwn'] = target_wwns
                # build target initiator map
                target_map = {}
                for initiator in connector['wwpns']:
                    target_map[initiator] = target_wwns
                data['initiator_target_map'] = target_map
                # delete host object
                self.driver.delete_host(connector['wwpns'])

        return {'driver_volume_type': 'fibre_channel',
                'data': data}

    def create_snapshot(self, snapshot):
        return self.driver.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        return self.driver.delete_snapshot(snapshot)

    def create_export(self, context, volume, connector):
        return self.driver.create_export(context, volume)

    def ensure_export(self, context, volume):
        return self.driver.ensure_export(context, volume)

    def remove_export(self, context, volume):
        return self.driver.remove_export(context, volume)
