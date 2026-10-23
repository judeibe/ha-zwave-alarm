/** Shapes returned by the integration's `zwave_alarm/*` websocket commands (see websocket_api.py). */
export type Category = "intrusion" | "life-safety";
export type Role = "administrator" | "member" | "guest";

export interface Sensor {
  id: string;
  zwaveNodeId: number;
  zoneId: string;
  name: string;
  category: Category;
  currentState: "normal" | "breached";
  /** The Z-Wave device's name in Home Assistant (device registry); absent when HA doesn't know the node. */
  haName?: string;
}
export interface Zone {
  id: string;
  name: string;
  description?: string | null;
  sensors: Sensor[];
}
export interface DiscoverableSensor {
  zwaveNodeId: number;
  name: string | null;
  manufacturer: string | null;
  product: string | null;
  status: "alive" | "dead" | "asleep";
  /** The Z-Wave device's name in Home Assistant (device registry); absent when HA doesn't know the node. */
  haName?: string;
}
/** A user never carries a code, only whether one is set. */
export interface AlarmUser {
  id: string;
  name: string;
  role: Role;
  hasCode?: boolean;
  haPersonId?: string | null;
  haUserId?: string | null;
}
export interface HaPerson {
  entity_id: string;
  name: string;
  user_id: string | null;
}
export interface Overview {
  zones: Zone[];
  discoverable: DiscoverableSensor[];
  /** Set when discovery alone failed (the service's Z-Wave driver isn't ready); the rest still loads. */
  discoverable_error?: { code: string; message: string } | null;
  users: AlarmUser[];
  ha_people: HaPerson[];
  ha_users: { id: string; name: string; is_admin: boolean }[];
}

/** The slice of Home Assistant's `hass` object the panel uses. */
export interface Hass {
  connection: { sendMessagePromise<T = unknown>(msg: Record<string, unknown>): Promise<T> };
}
/** Properties HA sets on a custom panel element. */
export interface PanelRoute {
  prefix: string;
  path: string;
}
