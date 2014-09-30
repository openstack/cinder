# Copyright (c) 2013 VMware, Inc.
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

"""
Classes for making VMware VI SOAP calls.
"""

import httplib
import urllib2

import suds

from cinder.i18n import _
from cinder.volume.drivers.vmware import error_util
from cinder.volume.drivers.vmware import vim_util

RESP_NOT_XML_ERROR = "Response is 'text/html', not 'text/xml'"
CONN_ABORT_ERROR = 'Software caused connection abort'
ADDRESS_IN_USE_ERROR = 'Address already in use'


def get_moref(value, type):
    """Get managed object reference.

    :param value: value for the managed object
    :param type: type of the managed object
    :return: Managed object reference with input value and type
    """
    moref = suds.sudsobject.Property(value)
    moref._type = type
    return moref


class VIMMessagePlugin(suds.plugin.MessagePlugin):

    def addAttributeForValue(self, node):
        """Helper to handle AnyType.

        suds does not handle AnyType properly.
        VI SDK requires type attribute to be set when AnyType is used

        :param node: XML value node
        """
        if node.name == 'value':
            node.set('xsi:type', 'xsd:string')

    def marshalled(self, context):
        """Marshal soap context.

        Provides the plugin with the opportunity to prune empty
        nodes and fixup nodes before sending it to the server.

        :param context: SOAP context
        """
        # suds builds the entire request object based on the wsdl schema.
        # VI SDK throws server errors if optional SOAP nodes are sent
        # without values, e.g. <test/> as opposed to <test>test</test>
        context.envelope.prune()
        context.envelope.walk(self.addAttributeForValue)


class Vim(object):
    """The VIM Object."""

    def __init__(self, protocol='https', host='localhost', wsdl_loc=None):
        """Create communication interfaces for initiating SOAP transactions.

        :param protocol: http or https
        :param host: Server IPAddress[:port] or Hostname[:port]
        """
        self._protocol = protocol
        self._host_name = host
        if not wsdl_loc:
            wsdl_loc = Vim._get_wsdl_loc(protocol, host)
        soap_url = vim_util.get_soap_url(protocol, host)
        self._client = suds.client.Client(wsdl_loc, location=soap_url,
                                          plugins=[VIMMessagePlugin()],
                                          cache=suds.cache.NoCache())
        self._service_content = self.RetrieveServiceContent('ServiceInstance')

    @staticmethod
    def _get_wsdl_loc(protocol, host_name):
        """Return default WSDL file location hosted at the server.

        :param protocol: http or https
        :param host_name: ESX/VC server host name
        :return: Default WSDL file location hosted at the server
        """
        return vim_util.get_soap_url(protocol, host_name) + '/vimService.wsdl'

    @property
    def service_content(self):
        return self._service_content

    @property
    def client(self):
        return self._client

    def __getattr__(self, attr_name):
        """Makes the API call and gets the result."""

        def retrieve_properties_ex_fault_checker(response):
            """Checks the RetrievePropertiesEx response for errors.

            Certain faults are sent as part of the SOAP body as property of
            missingSet. For example NotAuthenticated fault. The method raises
            appropriate VimFaultException when an error is found.

            :param response: Response from RetrievePropertiesEx API call
            """

            fault_list = []
            if not response:
                # This is the case when the session has timed out. ESX SOAP
                # server sends an empty RetrievePropertiesExResponse. Normally
                # missingSet in the returnval field has the specifics about
                # the error, but that's not the case with a timed out idle
                # session. It is as bad as a terminated session for we cannot
                # use the session. So setting fault to NotAuthenticated fault.
                fault_list = [error_util.NOT_AUTHENTICATED]
            else:
                for obj_cont in response:
                    if hasattr(obj_cont, 'missingSet'):
                        for missing_elem in obj_cont.missingSet:
                            fault_type = missing_elem.fault.fault.__class__
                            # Fault needs to be added to the type of fault
                            # for uniformity in error checking as SOAP faults
                            # define
                            fault_list.append(fault_type.__name__)
            if fault_list:
                exc_msg_list = ', '.join(fault_list)
                raise error_util.VimFaultException(fault_list,
                                                   _("Error(s): %s occurred "
                                                     "in the call to "
                                                     "RetrievePropertiesEx.") %
                                                   exc_msg_list)

        def vim_request_handler(managed_object, **kwargs):
            """Handler for VI SDK calls.

            Builds the SOAP message and parses the response for fault
            checking and other errors.

            :param managed_object:Managed object reference
            :param kwargs: Keyword arguments of the call
            :return: Response of the API call
            """

            try:
                if isinstance(managed_object, str):
                    # For strings use string value for value and type
                    # of the managed object.
                    managed_object = get_moref(managed_object, managed_object)
                request = getattr(self.client.service, attr_name)
                response = request(managed_object, **kwargs)
                if (attr_name.lower() == 'retrievepropertiesex'):
                    retrieve_properties_ex_fault_checker(response)
                return response

            except error_util.VimFaultException as excep:
                raise

            except suds.WebFault as excep:
                doc = excep.document
                detail = doc.childAtPath('/Envelope/Body/Fault/detail')
                fault_list = []
                if detail is not None:
                    for child in detail.getChildren():
                        fault_list.append(child.get('type'))
                raise error_util.VimFaultException(fault_list, excep)

            except AttributeError as excep:
                raise error_util.VimAttributeException(_("No such SOAP method "
                                                         "%(attr)s. Detailed "
                                                         "error: %(excep)s.") %
                                                       {'attr': attr_name,
                                                        'excep': excep})

            except (httplib.CannotSendRequest,
                    httplib.ResponseNotReady,
                    httplib.CannotSendHeader) as excep:
                raise error_util.SessionOverLoadException(_("httplib error in "
                                                            "%(attr)s: "
                                                            "%(excep)s.") %
                                                          {'attr': attr_name,
                                                           'excep': excep})

            except (urllib2.URLError, urllib2.HTTPError) as excep:
                raise error_util.VimConnectionException(
                    _("urllib2 error in %(attr)s: %(excep)s.") %
                    {'attr': attr_name,
                     'excep': excep})

            except Exception as excep:
                # Socket errors which need special handling for they
                # might be caused by server API call overload
                if (str(excep).find(ADDRESS_IN_USE_ERROR) != -1 or
                        str(excep).find(CONN_ABORT_ERROR)) != -1:
                    raise error_util.SessionOverLoadException(_("Socket error "
                                                                "in %(attr)s: "
                                                                "%(excep)s.") %
                                                              {'attr':
                                                               attr_name,
                                                               'excep': excep})
                # Type error that needs special handling for it might be
                # caused by server API call overload
                elif str(excep).find(RESP_NOT_XML_ERROR) != -1:
                    raise error_util.SessionOverLoadException(_("Type error "
                                                                "in %(attr)s: "
                                                                "%(excep)s.") %
                                                              {'attr':
                                                               attr_name,
                                                               'excep': excep})
                else:
                    raise error_util.VimException(_("Error in %(attr)s. "
                                                    "Detailed error: "
                                                    "%(excep)s.") %
                                                  {'attr': attr_name,
                                                   'excep': excep})
        return vim_request_handler

    def __repr__(self):
        return "VIM Object."

    def __str__(self):
        return "VIM Object."
