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
  batteryLevel?: number | null;
  connectivityStatus?: "online" | "offline";
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
/** A keypad as the service reports it (live from the integration's coordinator). */
export interface Keypad {
  nodeId: number;
  adapterId: string;
  label: string;
  connectivityStatus: "online" | "offline";
  batteryLevel: number | null;
}
export interface KeypadSettings {
  /** Arming from a keypad needs a valid user PIN; disarming always does. */
  requireCodeToArm: boolean;
}
/** Live alarm state from the integration's coordinator; `state` uses HA's alarm_control_panel strings. */
export interface PanelSummary {
  state: "disarmed" | "arming" | "armed_away" | "armed_home" | "pending" | "triggered" | null;
  armed_mode?: string | null;
  pending_delay_ends_at?: string | null;
}
export interface Overview {
  /** Null until the integration has received its first snapshot from the alarm service. */
  panel: PanelSummary | null;
  fault_count: number;
  faults: { offline: number; low_battery: number };
  zones: Zone[];
  discoverable: DiscoverableSensor[];
  /** Set when discovery alone failed (the service's Z-Wave driver isn't ready); the rest still loads. */
  discoverable_error?: { code: string; message: string } | null;
  users: AlarmUser[];
  ha_people: HaPerson[];
  ha_users: { id: string; name: string; is_admin: boolean }[];
  keypads: Keypad[];
  /** Null until the first snapshot, or when the service predates keypad settings. */
  keypad_settings: KeypadSettings | null;
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
