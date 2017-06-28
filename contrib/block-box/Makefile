CINDER_BRANCH ?= master # master, stable/ocata, refs/changes/67/418167/1
NAME_PREFIX ?= ""
PLATFORM ?= debian # ubuntu, centos
TAG ?= latest

all: base lvm devbox

base:
	docker build https://git.openstack.org/openstack/loci-cinder.git\#:$(PLATFORM) --tag cinder:$(TAG) --build-arg PROJECT_REF=$(CINDER_BRANCH)

lvm:
	docker build -t cinder-lvm -f ./docker_files/Dockerfile.cinder-lvm .

devbox:
	cp ../../test-requirements.txt ./docker_files/
	docker build -t cinder-devenv -f ./docker_files/Dockerfile.cinder-devenv .
	rm ./docker_files/test-requirements.txt
