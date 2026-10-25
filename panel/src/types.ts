/** Shapes returned by the integration's `zwave_alarm/*` websocket commands (see websocket_api.py). */
export type Category = "intrusion" | "life-safety";
export type Role = "administrator" | "member" | "guest" | "installer";

export type Placement = "MAIN_DOOR" | "SECONDARY_DOOR" | "WINDOW" | "ENTRYWAY" | "ROOM" | "GLASS_BREAK";
/** Entry and exit delay for one armed mode, whole seconds 0-180. */
export interface ModeDelays {
  entryDelaySec: number;
  exitDelaySec: number;
}
export type ArmedModeKey = "armed_home" | "armed_away";
export type Modes = Record<ArmedModeKey, ModeDelays>;
export type FaultReason = "open" | "offline" | "tampered" | "not_set_up" | "updating";
/** A sensor an arm was refused for until it is fixed or bypassed. */
export interface FaultedSensor {
  sensorId: string;
  name: string;
  zoneId: string;
  reason: FaultReason;
}
export interface AlarmEvent {
  id: string;
  type: "BURGLARY" | "SMOKE" | "CO" | "PANIC" | "FIRE_MEDICAL" | "DURESS" | "SOS" | "FLOOD_FREEZE";
  service: "police" | "fire" | "medical" | null;
  triggerDeviceId: string | null;
  startedAt: number;
  sirenState: "none" | "sounding" | "silenced" | "timed_out" | "stopped";
  dispatchState: "none" | "held" | "queued" | "cancelled";
}
export interface Siren {
  nodeId: number;
  kind: "BASE" | "DOME" | "OUTDOOR";
  name: string;
  durationSec: number;
  createdAt: number;
}
export type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
/** When a guest's code works on the keypad. A guest with none has unlimited access. */
export interface GuestSchedule {
  id: string;
  userId: string;
  name: string;
  days: Weekday[];
  allDay: boolean;
  start: string | null;
  end: string | null;
  timeZone: string | null;
}
export interface Sensor {
  id: string;
  zwaveNodeId: number;
  zoneId: string;
  name: string;
  category: Category;
  currentState: "normal" | "breached";
  batteryLevel?: number | null;
  /** Cover removed or not seated; absent from a service older than 3.3.0. */
  tampered?: boolean;
  connectivityStatus?: "online" | "offline";
  /** Null for life-safety sensors; absent on a service older than 3.0.0. */
  placement?: Placement | null;
  armedHome?: boolean;
  armedAway?: boolean;
  /** Notify only, never alarms. */
  alertsOnly?: boolean;
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
  /** An administrator's duress code; absent from a service older than 3.4.0. */
  hasDuressCode?: boolean;
  /** When a guest's or installer's access ends (epoch ms); an installer always has one (48 hours). */
  guestExpiresAt?: number | null;
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
export type ScheduleKind = "weekDay" | "yearDay" | "dailyRepeating";
/** Per schedule kind: true supported, false the lock has no slots, null not reported yet. */
export type ScheduleSupport = Record<ScheduleKind, boolean | null>;
/** What an enrolled lock supports; the panel hides controls that are false and says "not reported yet" for null. */
export interface LockCapabilities {
  /** Included with S0/S2; null while unknown. User codes and schedules need it. */
  secure: boolean | null;
  userCodes: boolean;
  userSlots: number;
  schedules: ScheduleSupport;
  alarmSettings: boolean;
}
/** A Schlage lock enrolled in the alarm system. The service sends enrolled locks only. */
export interface Lock {
  nodeId: number;
  model?: string | null;
  label?: string | null;
  connectivityStatus?: "online" | "offline";
  batteryLevel?: number | null;
  settings?: { pinLength?: number | null } & Record<string, unknown>;
  scheduleSlots?: Partial<Record<ScheduleKind, number>>;
  capabilities: LockCapabilities;
}
/** A lock paired to the controller but not enrolled (`GET /locks/available`): offered for enrolment, never a device. */
export interface AvailableLock {
  nodeId: number;
  model?: string | null;
  label?: string | null;
  connectivityStatus?: "online" | "offline";
  /** False when it was included without S0/S2, which enrolment refuses. */
  secure: boolean | null;
}
/** Reply to unenrolling: the service clears the lock's codes and schedules first; `cleared` is false when it could not. */
export interface UnenrollReply {
  node_id: number;
  cleared: boolean | null;
  failures: string[];
}
export type LockUserStatus = "enabled" | "disabled" | "available";
export interface WeekDaySchedule { weekday: number; startHour: number; startMinute: number; stopHour: number; stopMinute: number }
export interface YearDaySchedule {
  startYear: number; startMonth: number; startDay: number; startHour: number; startMinute: number;
  stopYear: number; stopMonth: number; stopDay: number; stopHour: number; stopMinute: number;
}
export interface DailyRepeatingSchedule { weekdays: number[]; startHour: number; startMinute: number; durationHour: number; durationMinute: number }
export type LockSchedule = WeekDaySchedule | YearDaySchedule | DailyRepeatingSchedule;
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
  /** Null until the first snapshot, or when the service predates per-mode delays (3.0.0). */
  modes: Modes | null;
  /** Alarm events that are still open, oldest first; absent from a service older than 3.2.0. */
  alarm_events?: AlarmEvent[];
  /** Enrolled sirens; absent from a service older than 3.3.0. */
  sirens?: Siren[];
  /** Enrolled locks only. */
  locks: Lock[];
  /** Paired to the Z-Wave controller but not enrolled: offered for enrolment, never shown as devices. */
  discoverable_locks: AvailableLock[];
  discoverable_locks_error?: { code: string; message: string } | null;
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
