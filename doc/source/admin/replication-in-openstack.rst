========================
Replication in OpenStack
========================

Replication provides a Disaster Recovery (DR) solution for mission-critical
workloads.
This guide will provide you step by step procedure on how to configure/utilize
the Cinder Replication feature in your own deployment. There are two parts
to the feature, Cinder side and Driver side. The Cinder side steps should be
common, however, the driver side steps may differ. This guide will use RBD
as the reference driver for the procedure.

Prerequisites
-------------

- Should have 2 backend clusters
- Cinder driver should support replication

See :doc:`../reference/support-matrix` to know about which backends support
replication.

Enable Replication
------------------

CEPH
^^^^

Reference: https://docs.ceph.com/en/latest/rbd/rbd-mirroring

*NOTE*: These steps are Ceph specific and are tested against Pacific release
of Ceph. Make sure that:

- A pool with the same name exists on both storage clusters.
- A pool contains journal-enabled images you want to mirror.

STEPS
"""""

* Get shell access for primary and secondary ceph clusters

.. code-block:: console

   site-a # sudo cephadm shell --fsid <PRIMARY_FSID> -c /etc/ceph/ceph.conf -k /etc/ceph/ceph.client.admin.keyring
   site-b # sudo cephadm shell --fsid <SECONDARY_FSID> -c /etc/ceph2/ceph.conf -k /etc/ceph2/ceph.client.admin.keyring

* Enable RBD mirroring on both hosts

.. code-block:: console

   site-a # ceph orch apply rbd-mirror --placement=<Primary Host>
   site-b # ceph orch apply rbd-mirror --placement=<Secondary Host>

* Enable image level mirroring

.. code-block:: console

    site-a # rbd mirror pool enable volumes image
    site-b # rbd mirror pool enable volumes image

* Bootstrap Peers

*NOTE*: These commands needs to be executed outside the cephadm shell.

.. code-block:: console

    site-a # sudo cephadm shell --fsid <PRIMARY_FSID> -c /etc/ceph/ceph.conf -k /etc/ceph/ceph.client.admin.keyring -- rbd mirror pool peer bootstrap create --site-name <FSID of site-a> <pool_name> | awk 'END{print}' > "$HOME/token_file"
    site-b # sudo cephadm shell --fsid <SECONDARY_FSID> -c /etc/ceph2/ceph.conf -k /etc/ceph2/ceph.client.admin.keyring -- rbd mirror pool peer bootstrap import --site-name <FSID of site-b> <pool_name> - < "$HOME/token_file"

Verification
""""""""""""

Verify that **Mode: image** and **Direction: rx-tx** are set in the below
output.

.. code-block:: console

    site-a # rbd mirror pool info volumes

    Mode: image
    Site Name: 55b6325e-e6b3-4b7c-91fd-64b5720c1685

    Peer Sites:

    UUID: 544777e2-4418-4dba-8f10-03238f63990d
    Name: 69cc3310-8dd4-4656-a75b-64d4890b0ca6
    Mirror UUID:
    Direction: rx-tx
    Client: client.rbd-mirror-peer

.. code-block:: console

    site-b # rbd mirror pool info volumes

    Mode: image
    Site Name: 69cc3310-8dd4-4656-a75b-64d4890b0ca6

    Peer Sites:

    UUID: a102dd15-cc37-4df6-acf1-266ec0248a37
    Name: 55b6325e-e6b3-4b7c-91fd-64b5720c1685
    Mirror UUID:
    Direction: rx-tx
    Client: client.rbd-mirror-peer

CINDER
^^^^^^

STEPS
"""""

* Set the ``replication_device`` values in ``cinder.conf`` file.

.. code-block:: console

    replication_device = backend_id:<unique_identifier>,conf:<ceph.conf path for site-b>,user:<user for site-b>,secret_uuid: <libvirt secret UUID>

* Create a replicated volume type. Note that we've used the
  ``volume_backend_name=ceph`` here which can be different for your
  deployment.

.. code-block:: console

    openstack volume type create --property replication_enabled='<is> True' --property volume_backend_name='ceph' ceph

Verification
""""""""""""

- Create a volume with replicated volume type

.. code-block:: console

    openstack volume create --type ceph --size 1 replicated-volume

- Confirm on RBD side that a replica is created

On site-a, you will see **mirroring primary: true**

.. code-block:: console

    site-a # rbd info volumes/volume-d217e292-0a98-4572-ae68-a4c40b73a278

    rbd image 'volume-d217e292-0a98-4572-ae68-a4c40b73a278':
            size 1 GiB in 256 objects
            order 22 (4 MiB objects)
            snapshot_count: 0
            id: a9ebeef62570
            block_name_prefix: rbd_data.a9ebeef62570
            format: 2
            features: layering, exclusive-lock, object-map, fast-diff, deep-flatten, journaling
            op_features:
            flags:
            create_timestamp: Thu May 15 14:15:04 2025
            access_timestamp: Thu May 15 14:15:04 2025
            modify_timestamp: Thu May 15 14:15:04 2025
            journal: a9ebeef62570
            mirroring state: enabled
            mirroring mode: journal
            mirroring global id: e8f583ed-abab-489c-b9d5-ef68c0a1b56f
            mirroring primary: true

On site-b, you will see **mirroring primary: false**

.. code-block:: console

    rbd ls volumes
    volume-d217e292-0a98-4572-ae68-a4c40b73a278

    rbd info volumes/volume-d217e292-0a98-4572-ae68-a4c40b73a278
    rbd image 'volume-d217e292-0a98-4572-ae68-a4c40b73a278':
            size 1 GiB in 256 objects
            order 22 (4 MiB objects)
            snapshot_count: 0
            id: 6a993924cde
            block_name_prefix: rbd_data.6a993924cde
            format: 2
            features: layering, exclusive-lock, object-map, fast-diff, deep-flatten, journaling
            op_features:
            flags:
            create_timestamp: Thu May 15 14:15:06 2025
            access_timestamp: Thu May 15 14:15:06 2025
            modify_timestamp: Thu May 15 14:15:06 2025
            journal: 6a993924cde
            mirroring state: enabled
            mirroring mode: journal
            mirroring global id: e8f583ed-abab-489c-b9d5-ef68c0a1b56f
            mirroring primary: false


Failover of a Boot From Volume (BFV) Server
-------------------------------------------

* Create a bootable replicated volume

.. code-block:: console

    openstack volume create --type ceph --image <Image-UUID> --size 1 test-bootable-replicated

* Launch a server from the volume

.. code-block:: console

    openstack server create --flavor c1 --nic=none --volume <Volume-UUID> test-bfv-server

* Create a file to write data to the VM disk

.. code-block:: console

    $ cat > failover-dr <<EOF
    > # Before failover
    > this should be consistent before/after failover
    > EOF

* Failover the replicated cinder backend

.. code-block:: console

    cinder failover-host <host>@<backend>

* Shelve/unshelve the server. (This is required to remove the connection
  from the volume in primary backend and create a new connection to the volume
  replica in secondary backend)

.. code-block:: console

    openstack server shelve <server-UUID>
    openstack server unshelve <server-UUID>

Verification
^^^^^^^^^^^^

* Verify that the connection is now made from secondary cluster

.. code-block:: console

    # In cinder-volume logs, we can see the ``hosts``, ``cluster_name`` and ``auth_username`` fields will point to secondary cluster
    Connection info returned from driver {'name': 'volumes/volume-e310359c-6587-4454-9a9c-a590b50dd4a5', 'hosts': ['127.0.0.1'], 'ports': ['6789'], 'cluster_name': 'ceph2', 'auth_enabled': True, 'auth_username': 'cinder2', 'secret_type': '***', 'secret_uuid': '***', 'volume_id': 'e310359c-6587-4454-9a9c-a590b50dd4a5', 'discard': True, 'qos_specs': None, 'access_mode': 'rw', 'encrypted': False, 'cacheable': False, 'driver_volume_type': 'rbd', 'attachment_id': 'b691cd50-83a1-4484-8081-7120a5cad054', 'enforce_multipath': True}

* Confirm that the data written before failover is persistent.

.. code-block:: console

    $ cat failover-dr
    # Before failover
    this should be consistent before/after failover

Failback of a Boot From Volume (BFV) Server
-------------------------------------------

* Create a file and write data to the VM disk. (Note that the volume backend
  is in failover mode and we are writing to the replica disk in secondary
  backend.)

.. code-block:: console

    $ cat > failover-dr <<EOF
    > # Before Failback
    > this should be consistent before/after failback
    > EOF

* Failback to primary backend

.. code-block:: console

    cinder failover-host <host>@<backend> --backend_id default

* Shelve/Unshelve the server (This is required to remove the connection
  from the replica volume in secondary backend and create a new connection to
  the original volume in primary backend)

.. code-block:: console

    openstack server shelve <server UUID>
    openstack server unshelve <server UUID>

Verification
^^^^^^^^^^^^

* Verify that the connection is now made from primary cluster

.. code-block:: console

    # In cinder-volume logs, we can see the ``hosts``, ``cluster_name`` and ``auth_username`` fields will point to primary cluster
    Connection info returned from driver {'name': 'volumes/volume-e310359c-6587-4454-9a9c-a590b50dd4a5', 'hosts': ['10.0.79.218'], 'ports': ['6789'], 'cluster_name': 'ceph', 'auth_enabled': True, 'auth_username': 'cinder', 'secret_type': '***', 'secret_uuid': '***', 'volume_id': 'e310359c-6587-4454-9a9c-a590b50dd4a5', 'discard': True, 'qos_specs': None, 'access_mode': 'rw', 'encrypted': False, 'cacheable': False, 'driver_volume_type': 'rbd', 'attachment_id': '2c8bb96b-5d5c-444c-aba5-13272b673b34', 'enforce_multipath': True}

* Confirm that the data written before failback is persistent.

.. code-block:: console

    $ cat failback-dr
    # Before Failback
    this should be consistent before/after failback

Failover of a External Data Volume
----------------------------------

* Create a test server

.. code-block:: console

    openstack server create --flavor c1 --nic=none --image <Image UUID> test-server

* Create and attach data volume to it

.. code-block:: console

    openstack volume create --type ceph --size 1 replicated-vol
    openstack server add volume <Server UUID> <Volume UUID>

* Write data to the volume. Note that creating a filesystem and mounting the
  device are implied here.

.. code-block:: console

    $ cat > failover-dr <<EOF
    > # Before failover
    > this should be consistent before/after failover
    > EOF

* Detach and attach the external data volume

.. code-block:: console

    openstack server remove volume <Server UUID> <Volume UUID>
    openstack server add volume <Server UUID> <Volume UUID>

Verification
^^^^^^^^^^^^

* Verify that the connection is now made from secondary cluster

.. code-block:: console

    # In cinder-volume logs, we can see the ``hosts``, ``cluster_name`` and ``auth_username`` fields will point to secondary cluster
    Connection info returned from driver {'name': 'volumes/volume-437573fd-08e2-42c9-b658-2f982bc0cdd2', 'hosts': ['127.0.0.1'], 'ports': ['6789'], 'cluster_name': 'ceph2', 'auth_enabled': True, 'auth_username': 'cinder2', 'secret_type': '***', 'secret_uuid': '***', 'volume_id': '437573fd-08e2-42c9-b658-2f982bc0cdd2', 'discard': True, 'qos_specs': None, 'access_mode': 'rw', 'encrypted': False, 'cacheable': False, 'driver_volume_type': 'rbd', 'attachment_id': '595bd265-4212-4d9a-8d48-ba6fb59d19fe', 'enforce_multipath': True}

* Verify that the data exists after failover.
  NOTE that in some cases, the data might/might not be persistent depending
  on the type of replication i.e. async or sync.

.. code-block:: console

    $ cat failover-dr
    # Before failover
    this should be consistent before/after failover

Failback of a External Data Volume
----------------------------------

* Create a file and write data to the external data volume. (Note that the
  volume backend is in failover mode and we are writing to the replica disk
  in secondary backend.)

.. code-block:: console

    $ cat > failback-dr <<EOF
    > # Before Failback
    > this should be consistent before/after failback
    > EOF

* Failback to primary backend

.. code-block:: console

    cinder failover-host <host>@<backend> --backend_id default

* Detach and attach the external data volume

.. code-block:: console

    openstack server remove volume <Server UUID> <Volume UUID>
    openstack server add volume <Server UUID> <Volume UUID>

Verification
^^^^^^^^^^^^

* Verify that the connection is now made from primary cluster

.. code-block:: console

    # In cinder-volume logs, we can see the ``hosts``, ``cluster_name`` and ``auth_username`` fields will point to primary cluster
    Connection info returned from driver {'name': 'volumes/volume-437573fd-08e2-42c9-b658-2f982bc0cdd2', 'hosts': ['10.0.79.218'], 'ports': ['6789'], 'cluster_name': 'ceph', 'auth_enabled': True, 'auth_username': 'cinder', 'secret_type': '***', 'secret_uuid': '***', 'volume_id': '437573fd-08e2-42c9-b658-2f982bc0cdd2', 'discard': True, 'qos_specs': None, 'access_mode': 'rw', 'encrypted': False, 'cacheable': False, 'driver_volume_type': 'rbd', 'attachment_id': 'b4e0c0a6-50b6-4ff3-83a5-a3da7be0e18c', 'enforce_multipath': True}

* Confirm that the data written before failback is persistent.
  NOTE that in some cases, the data might/might not be persistent depending
  on the type of replication i.e. async or sync.

.. code-block:: console

    $ cat failback-dr
    # Before Failback
    this should be consistent before/after failback
