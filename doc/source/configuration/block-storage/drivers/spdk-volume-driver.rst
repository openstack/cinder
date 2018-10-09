==========================================
Storage Performance Development Kit driver
==========================================

Storage Performance Development Kit (SPDK) is a user space, polled-mode,
asynchronous, lockless NVMe driver. It provides zero-copy, highly
parallel access directly to an SSD from a user space application.
SPDK provides NVMe-oF target that is capable of serving disks over
the network or to other processes.

Preparation
~~~~~~~~~~~

SPDK NVMe-oF target installation
--------------------------------

Follow instructions available on https://spdk.io/doc/nvmf.html to install
and configure environment with SPDK NVMe-oF target application.

Storage pools configuration
---------------------------

SPDK Cinder driver requires storage pools to be configured upfront
in SPDK NVMe-oF target application. SPDK driver uses Logical Volume
Stores (LVS) as storage pools. Details on configuring LVS are available
on https://spdk.io/doc/logical_volumes.html. After storage pools are
configured remote access has to be enabled. Launch
``scripts/rpc_http_proxy.py`` script from SPDK directory to start an http
server that will manage requests from volume driver.

Supported operations
~~~~~~~~~~~~~~~~~~~~

* Create, delete, attach, and detach volumes.
* Create, list, and delete volume snapshots.
* Create a volume from a snapshot.
* Copy an image to a volume.
* Copy a volume to an image.
* Clone a volume.
* Extend a volume.
* Get volume statistics.

Configuration
~~~~~~~~~~~~~

Use the following options to configure for the SPDK NVMe-oF transport:

.. code-block:: ini

        volume_driver = cinder.volume.drivers.spdk.SPDKDriver
        target_protocol = nvmet_rdma          # SPDK driver supports only nvmet_rdma target protocol
        target_helper = spdk-nvmeof           # SPDK volume driver requires SPDK NVMe-oF target driver
        target_ip_address = 192.168.0.1       # NVMe-oF target IP address
        target_port = 4260                    # NVMe-oF target port
        target_prefix = nqn.2014-08.org.spdk  # NVMe-oF target nqn prefix

.. config-table::
   :config-target: SPDK

   cinder.volume.targets.spdknvmf
