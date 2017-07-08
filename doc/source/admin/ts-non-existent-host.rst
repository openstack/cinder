=================
Non-existent host
=================

Problem
~~~~~~~

This error could be caused by a volume being exported outside of
OpenStack using a host name different from the system name that
OpenStack expects. This error could be displayed with the :term:`IQN <iSCSI
Qualified Name (IQN)>` if the host was exported using iSCSI.

.. code-block:: console

   2013-04-19 04:02:02.336 2814 ERROR cinder.openstack.common.rpc.common [-] Returning exception Not found (HTTP 404)
   NON_EXISTENT_HOST - HOST '10' was not found to caller.

Solution
~~~~~~~~

Host names constructed by the driver use just the local host name, not
the fully qualified domain name (FQDN) of the Compute host. For example,
if the FQDN was **myhost.example.com**, just **myhost** would be used as the
3PAR host name. IP addresses are not allowed as host names on the 3PAR
storage server.
