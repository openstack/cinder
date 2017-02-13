..
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.


Running Cinder API under Apache
===============================

Files
-----
Copy the file etc/cinder/api-httpd.conf to the appropriate location for your Apache server, most likely:

``/etc/httpd/conf.d/cinder_wsgi.conf``

Update this file to match your system configuration (for example, some distributions put httpd logs in the apache2 directory and some in the httpd directory).
Create the directory /var/www/cgi-bin/cinder/. You can either hard or soft link the file cinder/wsgi/wsgi.py to be osapi_volume under the /var/www/cgi-bin/cinder/ directory. For a distribution appropriate place, it should probably be copied to:

``/usr/share/openstack/cinder/httpd/cinder.py``

Cinder's primary configuration file (etc/cinder.conf) and the PasteDeploy configuration file (etc/cinder-paste.ini) must be readable to httpd in one of the default locations described in Configuring Cinder.


Access Control
--------------

If you are running with Linux kernel security module enabled (for example SELinux or AppArmor), make sure that the configuration file has the appropriate context to access the linked file.

