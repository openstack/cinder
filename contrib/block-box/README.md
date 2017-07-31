# block-box
Standalone Cinder Containerized using Docker Compose

## Cinder
Provides Block Storage as a service as part of the OpenStack Project.
This project deploys Cinder in containers using docker-compose and
also enabled the use of Cinder's noauth option which eliminates the
need for keystone.  One could also easily add keystone into the
compose file along with an init script to set up endpoints.

## LOCI (Lightweight Open Compute Initiative)
The block-box uses OpenStack Loci to build a base Cinder image to use
for each service.  The examples use Debian as the base OS, but you can
choose between Debian, CentOS and Ubuntu.

We're currently using Cinder's noauth option, but this pattern provides
flexibility to add a Keystone service if desired.

## To build
Start by building the required images.  This repo includes a Makefile to
enable building of openstack/loci images of Cinder.  The
Makefile includes variables to select between platform (debian, ubuntu or
centos) and also allows which branch of each project to build the image from.
This includes master, stable/xyz as well as patch versions.  Additional
variables are provided and can be passed to make using the `-e` option to
control things like naming and image tags.  See the Makefile for more info.

If you're going to utilize an external storage device (ie not using LVM), all
you need to build is the base Cinder image.  Set the variable in the Makefile
to choose the Cinder Branch you'd like to use and Platform then simply run:

```make base```

You can also build an image to run LVM (**NOTE**: This is dependent on the base cinder image):

```make lvm```

Finally the last image is a devenv image that will mount the cinder repo you've
checked out into a container and includes test-requirements:

```make devbox```

For more information and options, check out the openstack/loci page
on [github](https://github.com/openstack/loci).

**NOTE** The loci project is moving fairly quickly, and it may or may not
continue to be a straight forward light weight method of building container
Images. The build has been known to now work at times, and if it becomes
bloated or burdensome it's easy to swap in another image builder (or write your
own even).

This will result in some base images that we'll use:

1. cinder (openstack/loci image)
2. cinder-lvm (special cinder image with LVM config)
3. cinder-devenv (provides a Cinder development env container)

### cinder
Creates a base image with cinder installed via source.  This base image is
enough to run all of the services including api, scheduler and volume with
the exception of cinder-volume with the LVM driver which needs some extra
packages installed like LVM2 and iSCSI target driver.

Each Cinder service has an executable entrypoint at /usr/local/bin.

**NOTE** If you choose to build images from something other than the default Debian
base, you'll need to modify the Makefile for this image as well.

### cinder-lvm
This is a special image that is built from the base cinder image and adds the
necessary packages for LVM and iSCSI.

### cinder-devenv
You might want to generate a conf file, or if you're like me, use Docker to do
some of your Cinder development.  You can run this container which has all of
the current development packages and python test-requirements for Cinder.

You can pass in your current source directory from your local machine using -v
in your run command, here's a trivial example that generates a sample config
file.  Note we don't use tox because we're already in an isolated environment.

```shell
docker run -it -v /home/jgriffith/src/cinder:/cinder  \
  cinder-devenv \
  bash -c "cd cinder && oslo-config-generator \
  --config-file=cinder/config/cinder-config-generator.conf"
```

Keep in mind the command will execute and then exit, the result is written to
the cinder directory specified in the -v argument.  In this example for
instance the result would be a newly generated cinder.conf.sample file in
/home/jgriffith/src/cinder/etc/cinder

## Accessing via cinderclient
You can of course build a cinderclient container with a `cinder` entrypoint and
use that for access, but in order to take advantage of things like the
local-attach extension, you'll need to install the client tools on the host.

The current release version in pypi doesn't include noauth
support, so you'll need to install from source, but that's not hard:

```shell
sudo pip install pytz
sudo pip install git+https://github.com/openstack/python-cinderclient
sudo pip install git+https://github.com/openstack/python-brick-cinderclient-ext
```
Before using, you must specify these env variables at least,
``OS_AUTH_TYPE``, ``CINDER_ENDPOINT``, ``OS_PROJECT_ID``, ``OS_USERNAME``.
You can utilize our sample file ``cinder.rc``, then you can use client
to communicate with your containerized cinder deployment with noauth!!


Remember, to perform local-attach/local-detach of volumes you'll need to use
sudo.  To preserve your env variables don't forget to use `sudo -E cinder xxxxx`

## To run
docker-compose up -d

Don't forget to modify the `etc-cinder/cinder.conf` file as needed for your
specific driver.  We'll be adding support for the LVM driver and LIO Tgts
shortly, but for now you won't have much luck without using an external
device (no worries, there are over 80 to choose from).

**Note**: If you use ``cinder-lvm`` image, you must guarantee the required
volume group which is specified in the ``cinder.conf`` already exists in
the host environment before starting the service.

## Adding your own driver
We don't do multi-backend in this type of environment; instead we just add
another container running the backend we want.  We can easily add to the base
service we've create using additional compose files.

The file `docker-compose-add-vol-service.yml` provides an example additional
compose file that will create another cinder-volume service configured to run
the SolidFire backend.

After launching the main compose file:
```shell
docker-compose up -d
```

Once the services are initialized and the database is synchronized, you can add
another backend by running:
```shell
docker-compose -f ./docker-compose-add-vol-service.yml up -d
```

Note that things like network settings and ports are IMPORTANT here!!

## Access using the cinderclient container

You can use your own cinderclient and openrc, or use the provided cinderclient
container.  You'll need to make sure and specify to use the same network
that was used by compose.

```shell
docker run -it -e OS_AUTH_TYPE=noauth \
  -e CINDERCLIENT_BYPASS_URL=http://cinder-api:8776/v3 \
  -e OS_PROJECT_ID=foo \
  -e OS_VOLUME_API_VERSION=3.27 \
  --network blockbox_default cinderclient list
```

# Or without docker-compose
That's ok, you can always just run the commands yourself using docker run:
```shell

# We set passwords and db creation in the docker-entrypoint-initdb.d script
docker run -d -p 3306:3306 \
  -v ~/block-box/docker-entrypoint-initdb.d:/docker-entrypoint-initdb.d \
  --name mariadb \
  --hostname mariadb \
  -e MYSQL_ROOT_PASSWORD=password \
  mariadb

# Make sure the environment vars match the startup script for your database host
docker run -d -p 5000:5000 \
  -p 35357:35357 \
  --link mariadb \
  --name keystone \
  --hostname keystone \
  -e OS_PASSWORD=password \
  -e DEMO_PASSWORD=password \
  -e DB_HOST=mariadb \
  -e DB_PASSWORD=password \
  keystone

docker run -d -p 5672:5672 --name rabbitmq --hostname rabbitmq rabbitmq

docker run -d -p 8776:8776 \
  --link mariadb \
  --link rabbitmq \
  --name cinder-api \
  --hostname cinder-api \
  -v ~/block-box/etc-cinder:/etc/cinder \
  -v ~/block-box/init-scripts:/init-scripts
  cinder_debian sh /init-scripts/cinder-api.sh

docker run -d --name cinder-scheduler \
  --hostname cinder-scheduler \
  --link mariadb \
  --link rabbitmq \
  -v ~/block-box/etc-cinder:/etc/cinder \
  cinder_debian cinder-scheduler

docker run -d --name cinder-volume \
  --hostname cinder-volume \
  --link mariadb \
  --link rabbitmq \
  -v ~/block-box/etc-cinder:/etc/cinder \
  cinder-debian cinder-volume
```
