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

    def __init__(self, host, port, user, password):
        self.baseUrl = 'https://%s:%s/api/rest/' % (host, port)
        self.session = requests.Session()
        self.session.auth = (user, password)
        self.header = {}
        self.header['Content-Type'] = 'application/json; charset=utf-8'
        self.header['x-dell-api-version'] = '1.5'
        self.verify = False

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
        '''Open connection to Enterprise Manager.'''
        connection = StorageCenterApi(self.config.san_ip,
                                      self.config.dell_sc_api_port,
                                      self.config.san_login,
                                      self.config.san_password)
        connection.open_connection()
        return connection


class StorageCenterApi(object):

    '''StorageCenterApi

    Handles calls to EnterpriseManager via the REST API interface.
    '''

    APIVERSION = '1.0.1'

    def __init__(self, host, port, user, password):
        self.notes = 'Created by Dell Cinder Driver'
        self.client = HttpClient(host,
                                 port,
                                 user,
                                 password)

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

    def find_sc(self, ssn):
        '''This is really just a check that the sc is there and being managed by
        EM.
        '''
        r = self.client.get('StorageCenter/StorageCenter')
        result = self._get_result(r,
                                  'scSerialNumber',
                                  ssn)
        if result is None:
            LOG.error(_LE('Failed to find %(s)s.  Result %(r)s'),
                      {'s': ssn,
                       'r': r})
            raise exception.VolumeBackendAPIException(
                _('Failed to find Storage Center'))

        return self._get_id(result)

    # Volume functions

    def _create_folder(self, url, ssn, parent, folder):
        '''This is generic to server and volume folders.
        '''
        f = None
        payload = {}
        payload['Name'] = folder
        payload['StorageCenter'] = ssn
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

    def _create_folder_path(self, url, ssn, foldername):
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
                                      ssn,
                                      folderpath)
                if f is None:
                    found = False
            # We didn't find it so create it
            if found is False:
                f = self._create_folder(url,
                                        ssn,
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

    def _find_folder(self, url, ssn, foldername):
        '''Most of the time the folder will already have been created so
        we look for the end folder and check that the rest of the path is
        right.

        This is generic to server and volume folders.
        '''
        pf = PayloadFilter()
        pf.append('scSerialNumber', ssn)
        basename = os.path.basename(foldername)
        pf.append('Name', basename)
        # If we have any kind of path we add '/' to match the storage
        # center's convention and throw it into the filters.
        folderpath = os.path.dirname(foldername)
        if folderpath != '':
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

    def _create_volume_folder_path(self, ssn, foldername):
        return self._create_folder_path('StorageCenter/ScVolumeFolder',
                                        ssn,
                                        foldername)

    def _find_volume_folder(self, ssn, foldername):
        return self._find_folder('StorageCenter/ScVolumeFolder/GetList',
                                 ssn,
                                 foldername)

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

    def create_volume(self, name, size, ssn, volfolder):
        '''This creates a new volume on the storage center.  It
        will create it in volfolder.  If volfolder does not
        exist it will create it.  If it cannot create volfolder
        the volume will be created in the root.
        '''
        scvolume = None
        # Find our folder
        LOG.debug('Create Volume %(name)s %(ssn)s %(folder)s',
                  {'name': name,
                   'ssn': ssn,
                   'folder': volfolder})
        folder = self._find_volume_folder(ssn,
                                          volfolder)

        # Doesn't exist?  make it
        if folder is None:
            folder = self._create_volume_folder_path(ssn,
                                                     volfolder)

        # If we actually have a place to put our volume create it
        if folder is None:
            LOG.error(_LE('Unable to create folder %s'),
                      volfolder)

        # Create the volume
        payload = {}
        payload['Name'] = name
        payload['Notes'] = self.notes
        payload['Size'] = '%d GB' % size
        payload['StorageCenter'] = ssn
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
        if scvolume:
            LOG.info(_LI('Created volume %(instanceId)s: %(name)s'),
                     {'instanceId': scvolume['instanceId'],
                      'name': scvolume['name']})
        else:
            LOG.error(_LE('ScVolume returned success with empty payload.'
                          '  Attempting to locate volume'))
            # In theory it is there since success was returned.
            # Try one last time to find it before returning.
            scvolume = self.find_volume(ssn, name, None)

        return scvolume

    def find_volume(self, ssn, name=None, instanceid=None):
        '''search ssn for volume of name and/or instance id
        '''
        LOG.debug('finding volume %(sn)s : %(name)s : %(id)s',
                  {'sn': ssn,
                   'name': name,
                   'id': instanceid})
        pf = PayloadFilter()
        pf.append('scSerialNumber', ssn)
        # We need at least a name and or an instance id.  If we have
        # that we can find a volume.
        if instanceid is not None:
            pf.append('instanceId', instanceid)
        elif name is not None:
            pf.append('Name', name)
        else:
            return None
        r = self.client.post('StorageCenter/ScVolume/GetList',
                             pf.payload)
        if r.status_code != 200:
            LOG.debug('ScVolume GetList error %(i)s: %(c)d %(r)s',
                      {'i': instanceid,
                       'c': r.status_code,
                       'r': r.reason})
        return self._first_result(r)

    def delete_volume(self, ssn, name):
        # find our volume
        vol = self.find_volume(ssn, name, None)
        if vol is not None:
            r = self.client.delete('StorageCenter/ScVolume/%s'
                                   % self._get_id(vol))
            if r.status_code != 200:
                raise exception.VolumeBackendAPIException(
                    _('Error deleting volume %(ssn)s: %(sn)s: %(c)d %(r)s') %
                    {'ssn': ssn,
                     'sn': name,
                     'c': r.status_code,
                     'r': r.reason})
            # json return should be true or false
            return self._get_json(r)
        LOG.warning(_LW('delete_volume: unable to find volume %s'),
                    name)
        # If we can't find the volume then it is effectively gone.
        return True

    def _create_server_folder_path(self, ssn, foldername):
        return self._create_folder_path('StorageCenter/ScServerFolder',
                                        ssn,
                                        foldername)

    def _find_server_folder(self, ssn, foldername):
        return self._find_folder('StorageCenter/ScServerFolder/GetList',
                                 ssn,
                                 foldername)

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
    def _find_serveros(self, ssn, osname='Red Hat Linux 6.x'):
        '''Returns the serveros instance id of the specified osname.
        Required to create a server.
        '''
        pf = PayloadFilter()
        pf.append('scSerialNumber', ssn)
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

    def create_server_multiple_hbas(self, ssn, foldername, wwns):
        '''Same as create_server except it can take a list of hbas.  hbas
        can be wwns or iqns.
        '''
        # Add hbas
        scserver = None
        # Our instance names
        for wwn in wwns:
            if scserver is None:
                # Use the fist wwn to create the server.
                scserver = self.create_server(ssn,
                                              foldername,
                                              wwn,
                                              True)
            else:
                # Add the wwn to our server
                self._add_hba(scserver,
                              wwn,
                              True)
        return scserver

    def create_server(self, ssn, foldername, wwnoriscsiname, isfc=False):
        '''creates a server on the the storage center ssn.  Adds the first
        HBA to it.
        '''
        scserver = None
        payload = {}
        payload['Name'] = 'Server_' + wwnoriscsiname
        payload['StorageCenter'] = ssn
        payload['Notes'] = self.notes
        # We pick Red Hat Linux 6.x because it supports multipath and
        # will attach luns to paths as they are found.
        scserveros = self._find_serveros(ssn, 'Red Hat Linux 6.x')
        if scserveros is not None:
            payload['OperatingSystem'] = scserveros

        # Find our folder or make it
        folder = self._find_server_folder(ssn,
                                          foldername)
        if folder is None:
            folder = self._create_server_folder_path(ssn,
                                                     foldername)

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

    def find_server(self, ssn, instance_name):
        '''Hunts for a server by looking for an HBA with the server's IQN
        or wwn.

        If found, the server the HBA is attached to, if any, is returned.
        '''
        scserver = None
        # We search for our server by first finding our HBA
        hba = self._find_serverhba(ssn, instance_name)
        # Once created hbas stay in the system.  So it isn't enough
        # that we found one it actually has to be attached to a
        # server.
        if hba is not None and hba.get('server') is not None:
            pf = PayloadFilter()
            pf.append('scSerialNumber', ssn)
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

    def _find_serverhba(self, ssn, instance_name):
        '''Hunts for a sc server HBA by looking for an HBA with the
        server's IQN or wwn.

        If found, the sc server HBA is returned.
        '''
        scserverhba = None
        # We search for our server by first finding our HBA
        pf = PayloadFilter()
        pf.append('scSerialNumber', ssn)
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
            LOG.error(_LE('Unable to find FC intitiators'))
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
        LOG.debug('find_active_controller')
        activecontroller = None
        r = self.client.get('StorageCenter/ScVolume/%s/VolumeConfiguration'
                            % self._get_id(scvolume))
        if r.status_code == 200:
            volumeconfiguration = self._first_result(r)
            controller = volumeconfiguration.get('controller')
            activecontroller = self._get_id(controller)
        LOG.debug('activecontroller %s', activecontroller)
        return activecontroller

    def find_iscsi_properties(self, scvolume, ip=None, port=None):
        LOG.debug('enter find_iscsi_properties')
        LOG.debug('scvolume: %s', scvolume)
        activeindex = -1
        luns = []
        iqns = []
        portals = []
        access_mode = 'rw'
        mappings = self._find_mappings(scvolume)
        activecontroller = self._find_active_controller(scvolume)
        if len(mappings) > 0:
            for mapping in mappings:
                LOG.debug('mapping: %s', mapping)
                # find the controller port for this mapping
                cport = mapping.get('controllerPort')
                cportid = self._get_id(cport)
                domains = self._find_domains(cportid)
                if domains:
                    controllerport = self._find_controller_port(cportid)
                    LOG.debug('controllerport: %s', controllerport)
                    if controllerport is not None:
                        appendproperties = False
                        for d in domains:
                            LOG.debug('domain: %s', d)
                            ipaddress = d.get('targetIpv4Address',
                                              d.get('wellKnownIpAddress'))
                            portnumber = d.get('portNumber')
                            if ((ip is None or ip == ipaddress) and
                                    (port is None or port == portnumber)):
                                portal = (ipaddress + ':' +
                                          six.text_type(portnumber))
                                # I'm not sure when we can have more than
                                # one portal for a domain but since it is an
                                # array being returned it is best to check.
                                if portals.count(portal) == 0:
                                    appendproperties = True
                                    portals.append(portal)
                                else:
                                    LOG.debug('Domain %s has two portals.',
                                              self._get_id(d))
                        # We do not report lun and iqn info unless it is for
                        # the configured port OR the user has not enabled
                        # multipath.  (In which case ip and port sent in
                        # will be None).
                        if appendproperties is True:
                            iqns.append(controllerport.get('iscsiName'))
                            luns.append(mapping.get('lun'))
                            if activeindex == -1:
                                controller = controllerport.get('controller')
                                controllerid = self._get_id(controller)
                                if controllerid == activecontroller:
                                    activeindex = len(iqns) - 1
                        if mapping['readOnly'] is True:
                            access_mode = 'ro'

        if activeindex == -1:
            LOG.debug('Volume is not yet active on any controller.')
            activeindex = 0

        data = {'target_discovered': False,
                'target_iqns': iqns,
                'target_portals': portals,
                'target_luns': luns,
                'access_mode': access_mode
                }
        LOG.debug('find_iscsi_properties return: %s', data)

        return activeindex, data

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

    def get_storage_usage(self, ssn):
        '''get_storage_usage'''
        storageusage = None
        if ssn is not None:
            r = self.client.get('StorageCenter/StorageCenter/%s/StorageUsage'
                                % ssn)
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

    def create_view_volume(self, volname, volfolder, screplay):
        '''create_view_volume

        creates a new volume named volname in the folder
        volfolder from the screplay.
        '''
        # find our ssn and get our folder
        ssn = screplay.get('scSerialNumber')
        folder = self._find_volume_folder(ssn,
                                          volfolder)

        # Doesn't exist?  make it
        if folder is None:
            folder = self._create_volume_folder_path(ssn,
                                                     volfolder)

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

    def create_cloned_volume(self, volumename, volumefolder, scvolume):
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
                                            volumefolder,
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
