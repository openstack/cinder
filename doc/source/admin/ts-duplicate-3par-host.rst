===================
Duplicate 3PAR host
===================

Problem
~~~~~~~

This error may be caused by a volume being exported outside of OpenStack
using a host name different from the system name that OpenStack expects.
This error could be displayed with the :term:`IQN <iSCSI Qualified Name
(IQN)>` if the host was exported using iSCSI:

.. code-block:: console

   Duplicate3PARHost: 3PAR Host already exists: Host wwn 50014380242B9750 \
   already used by host cld4b5ubuntuW(id = 68. The hostname must be called\
   'cld4b5ubuntu'.

Solution
~~~~~~~~

Change the 3PAR host name to match the one that OpenStack expects. The
3PAR host constructed by the driver uses just the local host name, not
the fully qualified domain name (FQDN) of the compute host. For example,
if the FQDN was *myhost.example.com*, just *myhost* would be used as the
3PAR host name. IP addresses are not allowed as host names on the 3PAR
storage server.
