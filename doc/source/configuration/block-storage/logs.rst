===============================
Log files used by Block Storage
===============================

The corresponding log file of each Block Storage service is stored in
the ``/var/log/cinder/`` directory of the host on which each service
runs.

.. list-table:: **Log files used by Block Storage services**
   :header-rows: 1
   :widths: 10 20 10

   * - Log file
     - Service/interface (for CentOS, Fedora, openSUSE, Red Hat Enterprise Linux, and SUSE Linux Enterprise)
     - Service/interface (for Ubuntu and Debian)
   * - api.log
     - openstack-cinder-api
     - cinder-api
   * - cinder-manage.log
     - cinder-manage
     - cinder-manage
   * - scheduler.log
     - openstack-cinder-scheduler
     - cinder-scheduler
   * - volume.log
     - openstack-cinder-volume
     - cinder-volume

