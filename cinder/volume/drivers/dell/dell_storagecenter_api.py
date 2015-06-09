#    Copyright 2015 Dell Inc.
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
'''Interface for interacting with the Dell Storage Center array.'''

import json
import os.path

from oslo_log import log as logging
import requests
import six

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder import utils


LOG = logging.getLogger(__name__)


class PayloadFilter(object):

    '''PayloadFilter

    Simple class for creating filters for interacting with the Dell
    Storage API.

    Note that this defaults to "AND" filter types.
    '''

    def __init__(self):
        self.payload = {}
        self.payload['filterType'] = 'AND'
        self.payload['filters'] = []

    def append(self, name, val, filtertype='Equals'):
        if val is not None:
            apifilter = {}
            apifilter['attributeName'] = name
            apifilter['attributeValue'] = val
            apifilter['filterType'] = filtertype
            self.payload['filters'].append(apifilter)


class HttpClient(object):

    '''HttpClient

    Helper for making the REST calls.
    '''

    def __init__(self, host, port, user, password, verify):
        self.baseUrl = 'https://%s:%s/api/rest/' % (host, port)
        self.session = requests.Session()
        self.session.auth = (user, password)
        self.header = {}
        self.header['Content-Type'] = 'application/json; charset=utf-8'
        self.header['x-dell-api-version'] = '2.0'
        self.verify = verify

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.session.close()

    def __formatUrl(self, url):
        return '%s%s' % (self.baseUrl, url if url[0] != '/' else url[1:])

    @utils.retry(exceptions=(requests.ConnectionError, ))
    def get(self, url):
        return self.session.get(
            self.__formatUrl(url),
            headers=self.header,
            verify=self.verify)

    @utils.retry(exceptions=(requests.ConnectionError, ))
    def post(self, url, payload):
        return self.session.post(
            self.__formatUrl(url),
            data=json.dumps(payload,
                            ensure_ascii=False).encode('utf-8'),
            headers=self.header,
            verify=self.verify)

    @utils.retry(exceptions=(requests.ConnectionError, ))
    def put(self, url, payload):
        return self.session.put(
            self.__formatUrl(url),
            data=json.dumps(payload,
                            ensure_ascii=False).encode('utf-8'),
            headers=self.header,
            verify=self.verify)

    @utils.retry(exceptions=(requests.ConnectionError, ))
    def delete(self, url):
        return self.session.delete(
            self.__formatUrl(url),
            headers=self.header,
            verify=self.verify)


class StorageCenterApiHelper(object):

    '''StorageCenterApiHelper

    Helper class for API access.  Handles opening and closing the
    connection to the Storage Center.
    '''

    def __init__(self, config):
        self.config = config

    def open_connection(self):
        connection = None
        ssn = self.config.dell_sc_ssn
        LOG.info(_LI('open_connection to %(s)s at %(ip)s'),
                 {'s': ssn,
                  'ip': self.config.san_ip})
        if ssn:
            '''Open connection to Enterprise Manager.'''
            connection = StorageCenterApi(self.config.san_ip,
                                          self.config.dell_sc_api_port,
                                          self.config.san_login,
                                          self.config.san_password,
                                          self.config.dell_sc_verify_cert)
            # This instance is for a single backend.  That backend has a
            # few items of information we should save rather than passing them
            # about.
            connection.ssn = ssn
            connection.vfname = self.config.dell_sc_volume_folder
            connection.sfname = self.config.dell_sc_server_folder
            connection.open_connection()
        else:
            raise exception.VolumeBackendAPIException('Configuration error.  '
                                                      'dell_sc_ssn not set.')
        return connection


class StorageCenterApi(object):

    '''StorageCenterApi

    Handles calls to EnterpriseManager via the REST API interface.
    '''

    APIVERSION = '1.0.1'

    def __init__(self, host, port, user, password, verify):
        self.notes = 'Created by Dell Cinder Driver'
        self.ssn = None
        self.vfname = 'openstack'
        self.sfname = 'openstack'
        self.client = HttpClient(host,
                                 port,
                                 user,
                                 password,
                                 verify)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close_connection()

    def _path_to_array(self, path):
        array = []
        while True:
            (path, tail) = os.path.split(path)
            if tail == '':
                array.reverse()
                return array
            array.append(tail)

    def _first_result(self, blob):
        return self._get_result(blob, None, None)

    def _get_result(self, blob, attribute, value):
        rsp = None
        content = self._get_json(blob)
        if content is not None:
            # We can get a list or a dict or nothing
            if isinstance(content, list):
                for r in content:
                    if attribute is None or r.get(attribute) == value:
                        rsp = r
                        break
            elif isinstance(content, dict):
                if attribute is None or content.get(attribute) == value:
                    rsp = content
            elif attribute is None:
                rsp = content

        if rsp is None:
            LOG.debug('Unable to find result where %(attr)s is %(val)s',
                      {'attr': attribute,
                       'val': value})
            LOG.debug('Blob was %(blob)s', {'blob': blob.text})
        return rsp

    def _get_json(self, blob):
        try:
            return blob.json()
        except AttributeError:
            LOG.error(_LE('Error invalid json: %s'),
                      blob)
        return None

    def _get_id(self, blob):
        try:
            if isinstance(blob, dict):
                return blob.get('instanceId')
        except AttributeError:
            LOG.error(_LE('Invalid API object: %s'),
                      blob)
        return None

    def open_connection(self):
        # Authenticate against EM
        payload = {}
        payload['Application'] = 'Cinder REST Driver'
        payload['ApplicationVersion'] = self.APIVERSION
        r = self.client.post('ApiConnection/Login',
                             payload)
        if r.status_code != 200:
            LOG.error(_LE('Login error: %(c)d %(r)s'),
                      {'c': r.status_code,
                       'r': r.reason})
            raise exception.VolumeBackendAPIException(
                _('Failed to connect to Enterprise Manager'))

    def close_connection(self):
        r = self.client.post('ApiConnection/Logout',
                             {})
        if r.status_code != 204:
            LOG.warning(_LW('Logout error: %(c)d %(r)s'),
                        {'c': r.status_code,
                         'r': r.reason})
        self.client = None

    def find_sc(self):
        '''This is really just a check that the sc is there and being managed
        by EM.
        '''
        r = self.client.get('StorageCenter/StorageCenter')
        result = self._get_result(r,
                                  'scSerialNumber',
                                  self.ssn)
        if result is None:
            LOG.error(_LE('Failed to find %(s)s.  Result %(r)s'),
                      {'s': self.ssn,
                       'r': r})
            raise exception.VolumeBackendAPIException(
                _('Failed to find Storage Center'))

        return self._get_id(result)

    # Folder functions

    def _create_folder(self, url, parent, folder):
        '''This is generic to server and volume folders.
        '''
        f = None
        payload = {}
        payload['Name'] = folder
        payload['StorageCenter'] = self.ssn
        if parent != '':
            payload['Parent'] = parent
        payload['Notes'] = self.notes

        r = self.client.post(url,
                             payload)
        if r.status_code != 201:
            LOG.debug('%(u)s error: %(c)d %(r)s',
                      {'u': url,
                       'c': r.status_code,
                       'r': r.reason})
        else:
            f = self._first_result(r)
        return f

    def _create_folder_path(self, url, foldername):
        '''This is generic to server and volume folders.
        '''
        path = self._path_to_array(foldername)
        folderpath = ''
        instanceId = ''
        # Technically the first folder is the root so that is already created.
        found = True
        f = None
        for folder in path:
            folderpath = folderpath + folder
            # If the last was found see if this part of the path exists too
            if found:
                listurl = url + '/GetList'
                f = self._find_folder(listurl,
                                      folderpath)
                if f is None:
                    found = False
            # We didn't find it so create it
            if found is False:
                f = self._create_folder(url,
                                        instanceId,
                                        folder)
            # If we haven't found a folder or created it then leave
            if f is None:
                LOG.error(_LE('Unable to create folder path %s'),
                          folderpath)
                break
            # Next part of the path will need this
            instanceId = self._get_id(f)
            folderpath = folderpath + '/'
        return f

    def _find_folder(self, url, foldername):
        '''Most of the time the folder will already have been created so
        we look for the end folder and check that the rest of the path is
        right.

        This is generic to server and volume folders.
        '''
        pf = PayloadFilter()
        pf.append('scSerialNumber', self.ssn)
        basename = os.path.basename(foldername)
        pf.append('Name', basename)
        # If we have any kind of path we throw it into the filters.
        folderpath = os.path.dirname(foldername)
        if folderpath != '':
            # SC convention is to end with a '/' so make sure we do.
            folderpath += '/'
            pf.append('folderPath', folderpath)
        folder = None
        r = self.client.post(url,
                             pf.payload)
        if r.status_code == 200:
            folder = self._get_result(r,
                                      'folderPath',
                                      folderpath)
        else:
            LOG.debug('%(u)s error: %(c)d %(r)s',
                      {'u': url,
                       'c': r.status_code,
                       'r': r.reason})
        return folder

    def _find_volume_folder(self, create=False):
        folder = self._find_folder('StorageCenter/ScVolumeFolder/GetList',
                                   self.vfname)
        # Doesn't exist?  make it
        if folder is None and create is True:
            folder = self._create_folder_path('StorageCenter/ScVolumeFolder',
                                              self.vfname)
        return folder

    def _init_volume(self, scvolume):
        '''Maps the volume to a random server and immediately unmaps
        it.  This initializes the volume.

        Don't wig out if this fails.
        '''
        pf = PayloadFilter()
        pf.append('scSerialNumber', scvolume.get('scSerialNumber'), 'Equals')
        r = self.client.post('StorageCenter/ScServer/GetList', pf.payload)
        if r.status_code == 200:
            scservers = self._get_json(r)
            # Sort through the servers looking for one with connectivity.
            for scserver in scservers:
                # TODO(tom_swanson): Add check for server type.
                # This needs to be either a physical or virtual server.
                # Outside of tempest tests this should not matter as we only
                # "init" a volume to allow snapshotting of an empty volume.
                if scserver.get('status', '').lower() != 'down':
                    # Map to actually create the volume
                    self.map_volume(scvolume,
                                    scserver)
                    self.unmap_volume(scvolume,
                                      scserver)
                    break

    def create_volume(self, name, size):
        '''This creates a new volume on the storage center.  It
        will create it in a folder called self.vfname.  If self.vfname
        does not exist it will create it.  If it cannot create it
        the volume will be created in the root.
        '''
        LOG.debug('Create Volume %(name)s %(ssn)s %(folder)s',
                  {'name': name,
                   'ssn': self.ssn,
                   'folder': self.vfname})

        # Find our folder
        folder = self._find_volume_folder(True)

        # If we actually have a place to put our volume create it
        if folder is None:
            LOG.warning(_LW('Unable to create folder %s'),
                        self.vfname)

        # Init our return.
        scvolume = None

        # Create the volume
        payload = {}
        payload['Name'] = name
        payload['Notes'] = self.notes
        payload['Size'] = '%d GB' % size
        payload['StorageCenter'] = self.ssn
        if folder is not None:
            payload['VolumeFolder'] = self._get_id(folder)
        r = self.client.post('StorageCenter/ScVolume',
                             payload)
        if r.status_code == 201:
            scvolume = self._get_json(r)
        else:
            LOG.error(_LE('ScVolume create error %(name)s: %(c)d %(r)s'),
                      {'name': name,
                       'c': r.status_code,
                       'r': r.reason})
            return None
        if scvolume:
            LOG.info(_LI('Created volume %(instanceId)s: %(name)s'),
                     {'instanceId': scvolume['instanceId'],
                      'name': scvolume['name']})
        else:
            LOG.error(_LE('ScVolume returned success with empty payload.'
                          '  Attempting to locate volume'))
            # In theory it is there since success was returned.
            # Try one last time to find it before returning.
            scvolume = self.find_volume(name)

        return scvolume

    def _get_volume_list(self, name, filterbyvfname=True):
        '''Return the list of volumes with name of name.
        :param name: Volume name.
        :param filterbyvfname:  If true filters by the preset folder name.
        :return: Returns the scvolume or None.
        '''
        result = None
        pf = PayloadFilter()
        pf.append('scSerialNumber', self.ssn)
        # We need a name to find a volume.
        if name is not None:
            pf.append('Name', name)
        else:
            return None
        # set folderPath
        if filterbyvfname:
            vfname = (self.vfname if self.vfname.endswith('/')
                      else self.vfname + '/')
            pf.append('volumeFolderPath', vfname)
        r = self.client.post('StorageCenter/ScVolume/GetList',
                             pf.payload)
        if r.status_code != 200:
            LOG.debug('ScVolume GetList error %(n)s: %(c)d %(r)s',
                      {'n': name,
                       'c': r.status_code,
                       'r': r.reason})
        else:
            result = self._get_json(r)
        # We return None if there was an error and a list if the command
        # succeeded. It might be an empty list.
        return result

    def find_volume(self, name):
        '''Search self.ssn for volume of name.
        '''
        LOG.debug('Searching %(sn)s for %(name)s',
                  {'sn': self.ssn,
                   'name': name})

        # Cannot find a volume without the name
        if name is None:
            return None

        # Look for our volume in our folder.
        vollist = self._get_volume_list(name,
                                        True)
        # If an empty list was returned they probably moved the volumes or
        # changed the folder name so try again without the folder.
        if not vollist:
            LOG.debug('Cannot find volume %(n)s in %(v)s.  Searching SC.',
                      {'n': name,
                       'v': self.vfname})
            vollist = self._get_volume_list(name,
                                            False)

        # If multiple volumes of the same name are found we need to error.
        if len(vollist) > 1:
            # blow up
            raise exception.VolumeBackendAPIException(
                _('Multiple copies of volume %s found.') % name)

        # We made it and should have a valid volume.
        return None if not vollist else vollist[0]

    def delete_volume(self, name):
        # Delete our volume.
        vol = self.find_volume(name)
        if vol is not None:
            r = self.client.delete('StorageCenter/ScVolume/%s'
                                   % self._get_id(vol))
            if r.status_code != 200:
                raise exception.VolumeBackendAPIException(
                    _('Error deleting volume %(ssn)s: %(sn)s: %(c)d %(r)s') %
                    {'ssn': self.ssn,
                     'sn': name,
                     'c': r.status_code,
                     'r': r.reason})
            # json return should be true or false
            return self._get_json(r)
        LOG.warning(_LW('delete_volume: unable to find volume %s'),
                    name)
        # If we can't find the volume then it is effectively gone.
        return True

    def _find_server_folder(self, create=False):
        folder = self._find_folder('StorageCenter/ScServerFolder/GetList',
                                   self.sfname)
        if folder is None and create is True:
            folder = self._create_folder_path('StorageCenter/ScServerFolder',
                                              self.sfname)
        return folder

    def _add_hba(self, scserver, wwnoriscsiname, isfc=False):
        '''Adds an HBA to the scserver.  The HBA will be added
        even if it has not been seen by the storage center.
        '''
        payload = {}
        if isfc is True:
            payload['HbaPortType'] = 'FibreChannel'
        else:
            payload['HbaPortType'] = 'Iscsi'
        payload['WwnOrIscsiName'] = wwnoriscsiname
        payload['AllowManual'] = True
        r = self.client.post('StorageCenter/ScPhysicalServer/%s/AddHba'
                             % self._get_id(scserver),
                             payload)
        if r.status_code != 200:
            LOG.error(_LE('AddHba error: %(i)s to %(s)s : %(c)d %(r)s'),
                      {'i': wwnoriscsiname,
                       's': scserver['name'],
                       'c': r.status_code,
                       'r': r.reason})
            return False
        return True

    # We do not know that we are red hat linux 6.x but that works
    # best for red hat and ubuntu.  So, there.
    def _find_serveros(self, osname='Red Hat Linux 6.x'):
        '''Returns the serveros instance id of the specified osname.
        Required to create a server.
        '''
        pf = PayloadFilter()
        pf.append('scSerialNumber', self.ssn)
        r = self.client.post('StorageCenter/ScServerOperatingSystem/GetList',
                             pf.payload)
        if r.status_code == 200:
            oslist = self._get_json(r)
            for srvos in oslist:
                name = srvos.get('name', 'nope')
                if name.lower() == osname.lower():
                    # Found it return the id
                    return self._get_id(srvos)

        LOG.warning(_LW('ScServerOperatingSystem GetList return: %(c)d %(r)s'),
                    {'c': r.status_code,
                     'r': r.reason})
        return None

    def create_server_multiple_hbas(self, wwns):
        '''Same as create_server except it can take a list of hbas.  hbas
        can be wwns or iqns.
        '''
        # Add hbas
        scserver = None
        # Our instance names
        for wwn in wwns:
            if scserver is None:
                # Use the fist wwn to create the server.
                scserver = self.create_server(wwn,
                                              True)
            else:
                # Add the wwn to our server
                self._add_hba(scserver,
                              wwn,
                              True)
        return scserver

    def create_server(self, wwnoriscsiname, isfc=False):
        '''creates a server on the the storage center self.ssn.  Adds the first
        HBA to it.
        '''
        scserver = None
        payload = {}
        payload['Name'] = 'Server_' + wwnoriscsiname
        payload['StorageCenter'] = self.ssn
        payload['Notes'] = self.notes
        # We pick Red Hat Linux 6.x because it supports multipath and
        # will attach luns to paths as they are found.
        scserveros = self._find_serveros('Red Hat Linux 6.x')
        if scserveros is not None:
            payload['OperatingSystem'] = scserveros

        # Find our folder or make it
        folder = self._find_server_folder(True)

        # At this point it doesn't matter if the folder was created or not.
        # We just attempt to create the server.  Let it be in the root if
        # the folder creation fails.
        if folder is not None:
            payload['ServerFolder'] = self._get_id(folder)

        # create our server
        r = self.client.post('StorageCenter/ScPhysicalServer',
                             payload)
        if r.status_code != 201:
            LOG.error(_LE('ScPhysicalServer create error: %(i)s: %(c)d %(r)s'),
                      {'i': wwnoriscsiname,
                       'c': r.status_code,
                       'r': r.reason})
        else:
            # Server was created
            scserver = self._first_result(r)

            # Add hba to our server
            if scserver is not None:
                if not self._add_hba(scserver,
                                     wwnoriscsiname,
                                     isfc):
                    LOG.error(_LE('Error adding HBA to server'))
                    # Can't have a server without an HBA
                    self._delete_server(scserver)
                    scserver = None
        # Success or failure is determined by the caller
        return scserver

    def find_server(self, instance_name):
        '''Hunts for a server by looking for an HBA with the server's IQN
        or wwn.

        If found, the server the HBA is attached to, if any, is returned.
        '''
        scserver = None
        # We search for our server by first finding our HBA
        hba = self._find_serverhba(instance_name)
        # Once created hbas stay in the system.  So it isn't enough
        # that we found one it actually has to be attached to a
        # server.
        if hba is not None and hba.get('server') is not None:
            pf = PayloadFilter()
            pf.append('scSerialNumber', self.ssn)
            pf.append('instanceId', self._get_id(hba['server']))
            r = self.client.post('StorageCenter/ScServer/GetList',
                                 pf.payload)
            if r.status_code != 200:
                LOG.error(_LE('ScServer error: %(c)d %(r)s'),
                          {'c': r.status_code,
                           'r': r.reason})
            else:
                scserver = self._first_result(r)
        if scserver is None:
            LOG.debug('Server (%s) not found.',
                      instance_name)
        return scserver

    def _find_serverhba(self, instance_name):
        '''Hunts for a sc server HBA by looking for an HBA with the
        server's IQN or wwn.

        If found, the sc server HBA is returned.
        '''
        scserverhba = None
        # We search for our server by first finding our HBA
        pf = PayloadFilter()
        pf.append('scSerialNumber', self.ssn)
        pf.append('instanceName', instance_name)
        r = self.client.post('StorageCenter/ScServerHba/GetList',
                             pf.payload)
        if r.status_code != 200:
            LOG.debug('ScServerHba error: %(c)d %(r)s',
                      {'c': r.status_code,
                       'r': r.reason})
        else:
            scserverhba = self._first_result(r)
        return scserverhba

    def _find_domains(self, cportid):
        r = self.client.get('StorageCenter/ScControllerPort/%s/FaultDomainList'
                            % cportid)
        if r.status_code == 200:
            domains = self._get_json(r)
            return domains
        else:
            LOG.debug('FaultDomainList error: %(c)d %(r)s',
                      {'c': r.status_code,
                       'r': r.reason})
            LOG.error(_LE('Error getting FaultDomainList'))
        return None

    def _find_domain(self, cportid, domainip):
        '''Returns the fault domain which a given controller port can
        be seen by the server
        '''
        domains = self._find_domains(cportid)
        if domains:
            # Wiffle through the domains looking for our
            # configured ip.
            for domain in domains:
                # If this is us we return the port.
                if domain.get('targetIpv4Address',
                              domain.get('wellKnownIpAddress')) == domainip:
                    return domain
        return None

    def _find_fc_initiators(self, scserver):
        '''_find_fc_initiators

        returns the server's fc HBA's wwns
        '''
        initiators = []
        r = self.client.get('StorageCenter/ScServer/%s/HbaList'
                            % self._get_id(scserver))
        if r.status_code == 200:
            hbas = self._get_json(r)
            for hba in hbas:
                wwn = hba.get('instanceName')
                if (hba.get('portType') == 'FibreChannel' and
                        wwn is not None):
                    initiators.append(wwn)
        else:
            LOG.debug('HbaList error: %(c)d %(r)s',
                      {'c': r.status_code,
                       'r': r.reason})
            LOG.error(_LE('Unable to find FC initiators'))
        return initiators

    def get_volume_count(self, scserver):
        r = self.client.get('StorageCenter/ScServer/%s/MappingList'
                            % self._get_id(scserver))
        if r.status_code == 200:
            mappings = self._get_json(r)
            return len(mappings)
        # Panic mildly but do not return 0.
        return -1

    def _find_mappings(self, scvolume):
        '''find mappings

        returns the volume's mappings
        '''
        mappings = []
        if scvolume.get('active', False):
            r = self.client.get('StorageCenter/ScVolume/%s/MappingList'
                                % self._get_id(scvolume))
            if r.status_code == 200:
                mappings = self._get_json(r)
            else:
                LOG.debug('MappingList error: %(c)d %(r)s',
                          {'c': r.status_code,
                           'r': r.reason})
                LOG.error(_LE('Unable to find volume mappings: %s'),
                          scvolume.get('name'))
        else:
            LOG.error(_LE('_find_mappings: volume is not active'))
        return mappings

    def _find_controller_port(self, cportid):
        '''_find_controller_port

        returns the controller port dict
        '''
        controllerport = None
        r = self.client.get('StorageCenter/ScControllerPort/%s'
                            % cportid)
        if r.status_code == 200:
            controllerport = self._first_result(r)
        else:
            LOG.debug('ScControllerPort error: %(c)d %(r)s',
                      {'c': r.status_code,
                       'r': r.reason})
            LOG.error(_LE('Unable to find controller port: %s'),
                      cportid)
        return controllerport

    def find_wwns(self, scvolume, scserver):
        '''returns the lun and wwns of the mapped volume'''
        # Our returnables
        lun = None  # our lun.  We return the first lun.
        wwns = []  # list of targets
        itmap = {}  # dict of initiators and the associated targets

        # Make sure we know our server's initiators.  Only return
        # mappings that contain HBA for this server.
        initiators = self._find_fc_initiators(scserver)
        # Get our volume mappings
        mappings = self._find_mappings(scvolume)
        if len(mappings) > 0:
            # We check each of our mappings.  We want to return
            # the mapping we have been configured to use.
            for mapping in mappings:
                # Find the controller port for this mapping
                cport = mapping.get('controllerPort')
                controllerport = self._find_controller_port(
                    self._get_id(cport))
                if controllerport is not None:
                    # This changed case at one point or another.
                    # Look for both keys.
                    wwn = controllerport.get('wwn',
                                             controllerport.get('WWN'))
                    if wwn is None:
                        LOG.error(_LE('Find_wwns: Unable to find port wwn'))
                    serverhba = mapping.get('serverHba')
                    if wwn is not None and serverhba is not None:
                        hbaname = serverhba.get('instanceName')
                        if hbaname in initiators:
                            if itmap.get(hbaname) is None:
                                itmap[hbaname] = []
                            itmap[hbaname].append(wwn)
                            wwns.append(wwn)

                            mappinglun = mapping.get('lun')
                            if lun is None:
                                lun = mappinglun
                            elif lun != mappinglun:
                                LOG.warning(_LW('Inconsistent Luns.'))
        else:
            LOG.error(_LE('Find_wwns: Volume appears unmapped'))
        LOG.debug(lun)
        LOG.debug(wwns)
        LOG.debug(itmap)
        # TODO(tom_swanson): if we have nothing to return raise an exception
        # here.  We can't do anything with an unmapped volume.  We shouldn't
        # pretend we succeeded.
        return lun, wwns, itmap

    def _find_active_controller(self, scvolume):
        # Find the controller on which scvolume is active.
        actvctrl = None
        r = self.client.get('StorageCenter/ScVolume/%s/VolumeConfiguration'
                            % self._get_id(scvolume))
        if r.status_code == 200:
            volconfig = self._first_result(r)
            controller = volconfig.get('controller')
            actvctrl = self._get_id(controller)
        else:
            LOG.debug('VolumeConfiguration error: %(c)d %(r)s',
                      {'c': r.status_code,
                       'r': r.reason})
            LOG.error(_LE('Unable to retrieve VolumeConfiguration: %s'),
                      self._get_id(scvolume))
        LOG.debug('activecontroller %s', actvctrl)
        return actvctrl

    def _get_controller_id(self, mapping):
        # The mapping lists the associated controller.
        return self._get_id(mapping.get('controller'))

    def _get_domains(self, mapping):
        # Return a list of domains associated with this controller port.
        return self._find_domains(self._get_id(mapping.get('controllerPort')))

    def _get_iqn(self, mapping):
        # Get our iqn from our controller port.
        iqn = None
        cportid = self._get_id(mapping.get('controllerPort'))
        controllerport = self._find_controller_port(cportid)
        LOG.debug('controllerport: %s', controllerport)
        if controllerport:
            iqn = controllerport.get('iscsiName')
        return iqn

    def find_iscsi_properties(self, scvolume, ip=None, port=None):
        LOG.debug('enter find_iscsi_properties')
        LOG.debug('scvolume: %s', scvolume)
        active = -1
        up = -1
        access_mode = 'rw'
        portals = []
        luns = []
        iqns = []
        mappings = self._find_mappings(scvolume)
        if len(mappings) > 0:
            # In multipath (per Liberty) we will return all paths.  But
            # if multipath is not set (ip and port are None) then we need
            # to return a mapping from the controller on which the volume
            # is active.  So find that controller.
            actvctrl = self._find_active_controller(scvolume)
            for mapping in mappings:
                # The lun, ro mode and status are in the mapping.
                LOG.debug('mapping: %s', mapping)
                lun = mapping.get('lun')
                ro = mapping.get('readOnly', False)
                status = mapping.get('status')
                # Dig a bit to get our domains,IQN and controller id.
                domains = self._get_domains(mapping)
                iqn = self._get_iqn(mapping)
                ctrlid = self._get_controller_id(mapping)
                if domains and iqn is not None:
                    for d in domains:
                        LOG.debug('domain: %s', d)
                        ipaddress = d.get('targetIpv4Address',
                                          d.get('wellKnownIpAddress'))
                        portnumber = d.get('portNumber')
                        # We save our portal.
                        portals.append(ipaddress + ':' +
                                       six.text_type(portnumber))
                        iqns.append(iqn)
                        luns.append(lun)

                        # We've all the information.  We need to find
                        # the best single portal to return.  So check
                        # this one if it is on the right IP, port and
                        # if the access and status are correct.
                        if ((ip is None or ip == ipaddress) and
                                (port is None or port == portnumber)):

                            # We need to point to the best link.
                            # So state active and status up is preferred
                            # but we don't actually need the state to be
                            # up at this point.
                            if up == -1:
                                access_mode = 'rw' if ro is False else 'ro'
                                if actvctrl == ctrlid:
                                    active = len(iqns) - 1
                                    if status == 'Up':
                                        up = active
        # Make sure we found something to return.
        if len(luns) == 0:
            # Since we just mapped this and can't find that mapping the world
            # is wrong so we raise exception.
            raise exception.VolumeBackendAPIException(
                _('Unable to find iSCSI mappings.'))

        # Make sure we point to the best portal we can.  This means it is
        # on the active controller and, preferably, up.  If it isn't return
        # what we have.
        if up != -1:
            # We found a connection that is already up.  Return that.
            active = up
        elif active == -1:
            # This shouldn't be able to happen.  Maybe a controller went
            # down in the middle of this so just return the first one and
            # hope the ports are up by the time the connection is attempted.
            LOG.debug('Volume is not yet active on any controller.')
            active = 0

        data = {'target_discovered': False,
                'target_iqn': iqns[active],
                'target_iqns': iqns,
                'target_portal': portals[active],
                'target_portals': portals,
                'target_lun': luns[active],
                'target_luns': luns,
                'access_mode': access_mode
                }

        LOG.debug('find_iscsi_properties return: %s',
                  data)

        return data

    def map_volume(self, scvolume, scserver):
        '''map_volume

        The check for server existence is elsewhere;  does not create the
        server.
        '''
        # Make sure we have what we think we have
        serverid = self._get_id(scserver)
        volumeid = self._get_id(scvolume)
        if serverid is not None and volumeid is not None:
            payload = {}
            payload['server'] = serverid
            advanced = {}
            advanced['MapToDownServerHbas'] = True
            payload['Advanced'] = advanced
            r = self.client.post('StorageCenter/ScVolume/%s/MapToServer'
                                 % volumeid,
                                 payload)
            if r.status_code == 200:
                # We just return our mapping
                return self._first_result(r)
            # Should not be here.
            LOG.debug('MapToServer error: %(c)d %(r)s',
                      {'c': r.status_code,
                       'r': r.reason})
        # Error out
        LOG.error(_LE('Unable to map %(vol)s to %(srv)s'),
                  {'vol': scvolume['name'],
                   'srv': scserver['name']})
        return None

    def unmap_volume(self, scvolume, scserver):
        '''unmap_volume

        deletes all mappings to a server, not just the ones on the path
        defined in cinder.conf.
        '''
        rtn = True
        serverid = self._get_id(scserver)
        volumeid = self._get_id(scvolume)
        if serverid is not None and volumeid is not None:
            r = self.client.get('StorageCenter/ScVolume/%s/MappingProfileList'
                                % volumeid)
            if r.status_code == 200:
                profiles = self._get_json(r)
                for profile in profiles:
                    prosrv = profile.get('server')
                    if prosrv is not None and self._get_id(prosrv) == serverid:
                        r = self.client.delete(
                            'StorageCenter/ScMappingProfile/%s'
                            % self._get_id(profile))
                        if (r.status_code != 200 or r.ok is False):
                            LOG.debug('ScMappingProfile error: %(c)d %(r)s',
                                      {'c': r.status_code,
                                       'r': r.reason})
                            LOG.error(_LE('Unable to unmap Volume %s'),
                                      volumeid)
                            # 1 failed unmap is as good as 100.
                            # Fail it and leave
                            rtn = False
                            break
                        LOG.debug('Volume %(v)s unmapped from %(s)s',
                                  {'v': volumeid,
                                   's': serverid})
            else:
                LOG.debug('MappingProfileList error: %(c)d %(r)s',
                          {'c': r.status_code,
                           'r': r.reason})
                rtn = False
        return rtn

    def get_storage_usage(self):
        '''get_storage_usage'''
        storageusage = None
        if self.ssn is not None:
            r = self.client.get('StorageCenter/StorageCenter/%s/StorageUsage'
                                % self.ssn)
            if r.status_code == 200:
                storageusage = self._get_json(r)
            else:
                LOG.debug('StorageUsage error: %(c)d %(r)s',
                          {'c': r.status_code,
                           'r': r.reason})

        return storageusage

    def create_replay(self, scvolume, replayid, expire):
        '''create_replay

        expire is in minutes.
        one could snap a volume before it has been activated, so activate
        by mapping and unmapping to a random server and let them.  This
        should be a fail but the Tempest tests require it.
        '''
        replay = None
        if scvolume is not None:
            if (scvolume.get('active') is not True or
                    scvolume.get('replayAllowed') is not True):
                self._init_volume(scvolume)
            payload = {}
            payload['description'] = replayid
            payload['expireTime'] = expire
            r = self.client.post('StorageCenter/ScVolume/%s/CreateReplay'
                                 % self._get_id(scvolume),
                                 payload)
            if r.status_code != 200:
                LOG.debug('CreateReplay error: %(c)d %(r)s',
                          {'c': r.status_code,
                           'r': r.reason})
                LOG.error(_LE('Error creating replay.'))
            else:
                replay = self._first_result(r)
        return replay

    def find_replay(self, scvolume, replayid):
        '''find_replay

        searches for the replay by replayid which we store in the
        replay's description attribute
        '''
        replay = None
        r = self.client.get('StorageCenter/ScVolume/%s/ReplayList'
                            % self._get_id(scvolume))
        try:
            content = self._get_json(r)
            # This will be a list.  If it isn't bail
            if isinstance(content, list):
                for r in content:
                    # The only place to save our information with the public
                    # api is the description field which isn't quite long
                    # enough.  So we check that our description is pretty much
                    # the max length and we compare that to the start of
                    # the snapshot id.
                    description = r.get('description')
                    if (len(description) >= 30 and
                            replayid.startswith(description) is True and
                            r.get('markedForExpiration') is not True):
                        replay = r
                        break
        except Exception:
            LOG.error(_LE('Invalid ReplayList return: %s'),
                      r)

        if replay is None:
            LOG.debug('Unable to find snapshot %s',
                      replayid)

        return replay

    def delete_replay(self, scvolume, replayid):
        '''delete_replay

        hunts down a replay by replayid string and expires it.

        once marked for expiration we do not return the replay as
        a snapshot.
        '''
        LOG.debug('Expiring replay %s', replayid)
        replay = self.find_replay(scvolume,
                                  replayid)
        if replay is not None:
            r = self.client.post('StorageCenter/ScReplay/%s/Expire'
                                 % self._get_id(replay),
                                 {})
            if r.status_code != 204:
                LOG.debug('ScReplay Expire error: %(c)d %(r)s',
                          {'c': r.status_code,
                           'r': r.reason})
                return False
        # We either couldn't find it or expired it.
        return True

    def create_view_volume(self, volname, screplay):
        '''create_view_volume

        creates a new volume named volname from the screplay.
        '''
        folder = self._find_volume_folder(True)

        # payload is just the volume name and folder if we have one.
        payload = {}
        payload['Name'] = volname
        payload['Notes'] = self.notes
        if folder is not None:
            payload['VolumeFolder'] = self._get_id(folder)
        r = self.client.post('StorageCenter/ScReplay/%s/CreateView'
                             % self._get_id(screplay),
                             payload)
        volume = None
        if r.status_code == 200:
            volume = self._first_result(r)
        else:
            LOG.debug('ScReplay CreateView error: %(c)d %(r)s',
                      {'c': r.status_code,
                       'r': r.reason})

        if volume is None:
            LOG.error(_LE('Unable to create volume %s from replay'),
                      volname)

        return volume

    def create_cloned_volume(self, volumename, scvolume):
        '''create_cloned_volume

        creates a temporary replay and then creates a
        view volume from that.
        '''
        clone = None
        replay = self.create_replay(scvolume,
                                    'Cinder Clone Replay',
                                    60)
        if replay is not None:
            clone = self.create_view_volume(volumename,
                                            replay)
        else:
            LOG.error(_LE('Error: unable to snap replay'))
        return clone

    def expand_volume(self, scvolume, newsize):
        '''expand_volume'''
        payload = {}
        payload['NewSize'] = '%d GB' % newsize
        r = self.client.post('StorageCenter/ScVolume/%s/ExpandToSize'
                             % self._get_id(scvolume),
                             payload)
        vol = None
        if r.status_code == 200:
            vol = self._get_json(r)
        else:
            LOG.error(_LE('Error expanding volume %(n)s: %(c)d %(r)s'),
                      {'n': scvolume['name'],
                       'c': r.status_code,
                       'r': r.reason})
        if vol is not None:
            LOG.debug('Volume expanded: %(i)s %(s)s',
                      {'i': vol['instanceId'],
                       's': vol['configuredSize']})
        return vol

    def rename_volume(self, scvolume, name):
        payload = {}
        payload['Name'] = name
        r = self.client.post('StorageCenter/ScVolume/%s/Modify'
                             % self._get_id(scvolume),
                             payload)
        if r.status_code != 200:
            LOG.error(_LE('Error renaming volume %(o)s to %(n)s: %(c)d %(r)s'),
                      {'o': scvolume['name'],
                       'n': name,
                       'c': r.status_code,
                       'r': r.reason})
            return False
        return True

    def _delete_server(self, scserver):
        '''_delete_server

        Just give it a shot.  If it fails it doesn't matter to cinder.
        '''
        if scserver.get('deleteAllowed') is True:
            r = self.client.delete('StorageCenter/ScServer/%s'
                                   % self._get_id(scserver))
            LOG.debug('ScServer %(i)s delete return: %(c)d %(r)s',
                      {'i': self._get_id(scserver),
                       'c': r.status_code,
                       'r': r.reason})
        else:
            LOG.debug('_delete_server: deleteAllowed is False.')
