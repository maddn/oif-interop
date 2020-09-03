package com.tailf.packages.ned.onftapi;

import java.util.Arrays;
import java.util.List;
import java.util.Map.Entry;

import com.grack.nanojson.JsonObject;
import com.tailf.navu.NavuNode;
import com.tailf.ned.NedMux;
import com.tailf.ned.NedWorker;
import com.tailf.packages.ned.nedcom.NavuUtils;
import com.tailf.packages.ned.nedcom.JsonTransforms;
import com.tailf.packages.ned.nedcom.restconf.NedComGenericRestConfBase;

public class OnfTapiRestConfNedGeneric extends NedComGenericRestConfBase {

    private static String NED_SETTING_RESTCONF_DEVIATION_DROP_UUID = "restconf/deviations/drop-connectivity-service-uuid";
    private boolean dropConnectivityServiceUuid = false;

    /**
     * Default constructor.
     */
    public OnfTapiRestConfNedGeneric() {
        super();
    }

    /**
     * Constructor
     *
     *
     * @param device
     *            - Device id
     * @param mux
     *            - NED Mux
     * @param worker
     *            - NED Worker
     * @throws Exception
     */
    public OnfTapiRestConfNedGeneric(String deviceId, NedMux mux, boolean trace,
                                     NedWorker worker) throws Exception {
        super(deviceId, mux, true, worker);
        dropConnectivityServiceUuid = nedSettings.getBoolean(NED_SETTING_RESTCONF_DEVIATION_DROP_UUID, false);
    }

    /**
     * Apply JSON transforms on outbound messages. This method is intended
     * to be used by the inheriting sub class for doing custom adaptions of
     * of the messages for devices that deviate from the RESTCONF specification.
     * @param node - Corresponding node in config tree.
     * @param path - The RESTCONF path to be used when doing the operation.
     * @param json - JSON object containing the data below the node.
     * @param op   - The RESTCONF operation to be used.
     * @return transformed JSON object
     */
    @Override
    protected JsonObject applyOutboundTransforms(NavuNode node, StringBuilder path,
                                                 JsonObject json, OutBoundOp op) throws Exception {
        if (op == OutBoundOp.POST) {
            String module = NavuUtils.getDataModel(node);
            for (Entry<String, Object> e : json.entrySet()) {
                if (!e.getKey().contains(":")) {
                    json.put(String.format("%s:%s", module, e.getKey()), e.getValue());
                    json.remove(e.getKey());
                }
            }
        }

        if (dropConnectivityServiceUuid) {
            if (op == OutBoundOp.POST &&
                path.toString().equals("/data/tapi-common:context/tapi-connectivity:connectivity-context") &&
                json != null) {
                if (json.has("connectivity-service")) {
                    JsonObject jsonConnService = json.getObject("connectivity-service");
                    List<String> names = Arrays.asList("uuid");
                    JsonTransforms.deleteNodesWithName(jsonConnService, names);
                }
            }
        }

        return json;
    }


    /**
     * Apply JSON transforms on in bound messages. This method is intended
     * to be used by the inheriting sub class for doing custom adaptions of
     * of the messages for devices that deviate from the RESTCONF specification.

     * The method is called twice. First before the GET call, then again after.
     * Makes it possible to first transform the path, then the fetched payload.
     * @param node - Corresponding node in config tree.
     * @param path - Path to be used in the RESTCONF GET operation
     * @param json - JSON object containing the data to be populated under
     *               the node.
     * @return transformed JSON object
     */
    @Override
    protected JsonObject applyInboundTransforms(NavuNode node, StringBuilder path,
                                                JsonObject config) throws Exception {
        // Override and customize in sub class
        return config;
    }

    /**
     * Instantiate a custom RESTCONF Client. Only needed if the subclass
     * needs to instantiate a custom RESTCONF client.
     *
     * For example if adaptions need to be  made for special authentication
     * towards the device.
     * @param worker - The NED worker
     * @throws Exception
     */
    @Override
    protected void createConnection(NedWorker worker) throws Exception {
        super.createConnection(worker);
    }

    /**
     * Read all NED settings and setup instance variables accordingly.
     * Can extended/overridden by the inheriting sub class.
     */
    @Override
    protected void readNedSettings(NedWorker worker) {
        super.readNedSettings(worker);
    }

}
