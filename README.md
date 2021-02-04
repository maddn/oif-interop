# Overview

This repository contains the following NSO packages developed for the 2020 OIF
interop testing:

- **openconfig-open-terminals:** This package provides a service called
  `ot-connectivity` which will configure two open terminal device end points
  (client port, optical channel and line port on each device). In addition, the
  package provides several actions to read and cache the inventory operational
  data from an open terminal device (this data is used by the service).

- **tapi-ols:** This package provides a service called `ols-connectivity` which
  will provision a T-API connectivity service on an OLS T-API controller. It
  also contains a CDB subscriber and associated actions for receiving T-API SSE
  notifications from the controller.

- **tapi-disaggregated:** This package depends on the `tapi-ols` and
  `openconfig-open-terminal` packages. It contains the T-API yang models and an
  action to convert existing OpenConfig open terminal devices into the T-API
  format. It also adds a servicepoint to the T-API connectivity-service to
  provision the end-to-end service across the open terminals and OLS.

- **openconfig-ot-cisco-nc-1.0:** This is the OpenConfig NED with the optical
  transport YANG modules and Cisco deviation files. This can also be built
  using the NETCONF NED builder (see script folder for an example)

The T-API NED is also required (onf-tapi_rc) but not included in this repo.

The test folder contains automated LUX tests for the T-API uses from the
interop.

