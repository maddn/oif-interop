# Configuration
DRNED  ?= ../../../drned
NEDDIR ?= $(shell (cd ../.. && pwd))

SIMPLE_FILES=--fname='simple_tests/*.txt' \
	--fname='simple_tests/*.cfg'

all: 10min 100min 1000min

include $(DRNED)/make/Makefile

OPT = -s --tb=short --device=netsim-0

# Test targets for development use
10min: simple_tests
	py.test -s --tb=short -k test_package
.PHONY: 10min

100min:
	py.test $(OPT) -k test_lux

.PHONY: 100min

1000min:
	py.test $(OPT) -k test_incomplete_single
.PHONY: 1000min

# Run simple tests from simple_tests directory
simple_tests:
ifeq ($(wildcard simple_tests/init_state.init),)
	py.test $(OPT) -k test_template_set $(SIMPLE_FILES)
else
	py.test $(OPT) -k test_template_set $(SIMPLE_FILES) \
		--init=simple_tests/init_state.init
endif
.PHONY: simple_tests

release_test:
# Run the PKG reload test before every release
	py.test -s --tb=short -k 'test_pkg_upgrade' --device=netsim-0
	py.test -s --tb=short --device=netsim-0 -k 'test_ncs_pkg_reload' \
		--fname='simple_tests/*.txt' \
		--fname='simple_tests/*.cfg'
.PHONY: release_test
