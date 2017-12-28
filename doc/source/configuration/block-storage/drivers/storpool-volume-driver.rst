======================
StorPool volume driver
======================

StorPool is distributed data storage software running on standard x86
servers.  StorPool aggregates the performance and capacity of all drives
into a shared pool of storage distributed among the servers.  Within
this storage pool the user creates thin-provisioned volumes that are
exposed to the clients as block devices.  StorPool consists of two parts
wrapped in one package - a server and a client.  The StorPool server
allows a hypervisor to act as a storage node, while the StorPool client
allows a hypervisor node to access the storage pool and act as a compute
node.  In OpenStack terms the StorPool solution allows each hypervisor
node to be both a storage and a compute node simultaneously.

Prerequisites
-------------

* The controller and all the compute nodes must have access to the StorPool
  API service.

* All nodes where StorPool-backed volumes will be attached must have access to
  the StorPool data network and run the ``storpool_block`` service.

* If StorPool-backed Cinder volumes need to be created directly from Glance
  images, then the node running the ``cinder-volume`` service must also have
  access to the StorPool data network and run the ``storpool_block`` service.

* All nodes that need to access the StorPool API (the compute nodes and
  the node running the ``cinder-volume`` service) must have the following
  packages installed:

  * storpool-config (part of the StorPool installation)
  * the storpool Python bindings package
  * the storpool.spopenstack Python helper package

Configuring the StorPool volume driver
--------------------------------------

A valid ``/etc/storpool.conf`` file is required; please contact the StorPool
support team for assistance.

The StorPool Cinder volume driver has two configuration options that may
be specified both in the global configuration (e.g. in a ``cinder.conf``
volume backend definition) and per volume type:

- ``storpool_template``: specifies the StorPool template (replication,
  placement, etc. specifications defined once and used for multiple
  volumes and snapshots) to use for the Cinder volume type or, if
  specified globally, as a default value for Cinder volumes.  There is
  no default value for this option, see ``storpool_replication``.

- ``storpool_replication``: if ``storpool_template`` is not set,
  the volume will be created with the specified chain replication and
  with the default placement constraints for the StorPool cluster.
  The default value for the chain replication is 3.

Using the StorPool volume driver
--------------------------------

The most common use for the Cinder StorPool volume driver is probably
attaching volumes to Nova instances.  For this to work, the ``nova-compute``
service and the ``os-brick`` library must recognize the "storpool" volume
attachment driver; please contact the StorPool support team for more
information.

Currently there is no StorPool driver for Nova ephemeral volumes; to run
Nova instances with a StorPool-backed volume as a root device, create
a Cinder volume with the root filesystem image, make a snapshot, and let
Nova create the instance with a root device as a new volume created from
that snapshot.
