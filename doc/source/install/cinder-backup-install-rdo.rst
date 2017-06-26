:orphan:

Install and configure the backup service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optionally, install and configure the backup service. For simplicity,
this configuration uses the Block Storage node and the Object Storage
(swift) driver, thus depending on the
`Object Storage service <https://docs.openstack.org/project-install-guide/object-storage/ocata/>`_.

.. note::

   You must :ref:`install and configure a storage node <cinder-storage>` prior
   to installing and configuring the backup service.

Install and configure components
--------------------------------

.. note::

   Perform these steps on the Block Storage node.

#. Install the packages:

   .. code-block:: console

      # yum install openstack-cinder


#. Edit the ``/etc/cinder/cinder.conf`` file
   and complete the following actions:

   #. In the ``[DEFAULT]`` section, configure backup options:

      .. path /etc/cinder/cinder.conf
      .. code-block:: ini

         [DEFAULT]
         # ...
         backup_driver = cinder.backup.drivers.swift
         backup_swift_url = SWIFT_URL


      Replace ``SWIFT_URL`` with the URL of the Object Storage service. The
      URL can be found by showing the object-store API endpoints:

      .. code-block:: console

       $ openstack catalog show object-store


Finalize installation
---------------------

Start the Block Storage backup service and configure it to
start when the system boots:

.. code-block:: console

   # systemctl enable openstack-cinder-backup.service
   # systemctl start openstack-cinder-backup.service
