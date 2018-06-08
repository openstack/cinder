===============================
NexentaEdge NBD & iSCSI drivers
===============================

NexentaEdge is designed from the ground-up to deliver high performance Block
and Object storage services and limitless scalability to next generation
OpenStack clouds, petabyte scale active archives and Big Data applications.
NexentaEdge runs on shared nothing clusters of industry standard Linux
servers, and builds on Nexenta IP and patent pending Cloud Copy On Write (CCOW)
technology to break new ground in terms of reliability, functionality and cost
efficiency.

For NexentaEdge user documentation, visit https://nexentaedge.github.io.


iSCSI driver
~~~~~~~~~~~~

The NexentaEdge cluster must be installed and configured according to the
relevant Nexenta documentation. A cluster, tenant, bucket must be pre-created,
as well as an iSCSI service on the NexentaEdge gateway node.

The NexentaEdge iSCSI driver is selected using the normal procedures for one
or multiple back-end volume drivers.

You must configure these items for each NexentaEdge cluster that the iSCSI
volume driver controls:

#. Make the following changes on the volume node ``/etc/cinder/cinder.conf``
   file.

   .. code-block:: ini

      # Enable Nexenta iSCSI driver
      volume_driver = cinder.volume.drivers.nexenta.nexentaedge.iscsi.NexentaEdgeISCSIDriver

      # Specify the ip address for Rest API (string value)
      nexenta_rest_address = MANAGEMENT-NODE-IP

      # Port for Rest API (integer value)
      nexenta_rest_port=8080

      # Protocol used for Rest calls (string value, default=htpp)
      nexenta_rest_protocol = http

      # Username for NexentaEdge Rest (string value)
      nexenta_rest_user=USERNAME

      # Password for NexentaEdge Rest (string value)
      nexenta_rest_password=PASSWORD

      # Path to bucket containing iSCSI LUNs (string value)
      nexenta_lun_container = CLUSTER/TENANT/BUCKET

      # Name of pre-created iSCSI service (string value)
      nexenta_iscsi_service = SERVICE-NAME

      # IP address of the gateway node attached to iSCSI service above or
      # virtual IP address if an iSCSI Storage Service Group is configured in
      # HA mode (string value)
      nexenta_client_address = GATEWAY-NODE-IP


#. Save the changes to the ``/etc/cinder/cinder.conf`` file and
   restart the ``cinder-volume`` service.

Supported operations
--------------------

* Create, delete, attach, and detach volumes.

* Create, list, and delete volume snapshots.

* Create a volume from a snapshot.

* Copy an image to a volume.

* Copy a volume to an image.

* Clone a volume.

* Extend a volume.

Driver options
~~~~~~~~~~~~~~

Nexenta Driver supports these options:

.. include:: ../../tables/cinder-nexenta_edge.inc
