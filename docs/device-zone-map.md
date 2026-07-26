# Device Zone Map

## What it is and why it exists

FortiGate devices use device-specific interface names (`port3`, `dmz1`, `wan2`) that have no inherent meaning outside the device. The 4THealth policy system uses abstract zone names (`NSS OT-All`, `NSS IT DMZ`) to express what traffic is allowed between network segments. `device_zone_map.yaml` is the translation layer — it records, for each FortiGate interface on each device, which 4THealth policy zone that interface belongs to.

## How the analyze-request workflow uses it

When you run `/analyze-request`, step 4 calls `get_interface_map(adom, device)` on the relevant FortiGate. The system now enriches each interface entry with two additional fields:

- `policy_zone` — the 4THealth zone name pulled from `device_zone_map.yaml`, or `null` if the interface has no entry
- `zone_map_missing` — `true` if no mapping exists for this interface

The top-level return dict also includes a `zone_map_warnings` list. Any interface that is part of a proposed rule but lacks a `policy_zone` mapping appears in this list.

Step 7 (CLI generation) uses the `policy_zone` value to name policy rules correctly, e.g. `CHG0012345_OT_LAN_TO_IT_001`. If an interface is unmapped, the generated `.conf` file substitutes `UNKNOWN_ZONE` as a placeholder and adds a comment flagging it, and the HTML report includes a warning box listing the unmapped interfaces.

**When you see a zone_map warning:** add the missing entry (see below), then re-run the analysis. Do not submit the generated `.conf` to CAB with `UNKNOWN_ZONE` in it.

## The four ways to populate the file

### 1. Bootstrap from FortiManager (recommended first step)

```bash
python scripts/import_zone_map.py --from-fortimanager
```

This queries FortiManager for all ADOMs and devices, then writes every device and interface into `device_zone_map.yaml` with `policy_zone: null` placeholders. Existing entries are not overwritten — it only adds new devices and interfaces.

After running it, open `device_zone_map.yaml` and fill in the `policy_zone` value for each interface. Use `check_ip_traffic` or `get_zones()` to confirm the exact 4THealth zone name (names must match exactly — see the quick reference in `docs/zone-name-mapping.md`).

Re-run this command whenever new devices are added to FortiManager. It is safe to run repeatedly.

### 2. Import from CSV

```bash
python scripts/import_zone_map.py --from-csv interfaces.csv
```

Use this when a colleague has already filled in a spreadsheet with zone mappings. The CSV must have these columns in this order:

```
device,interface,alias,policy_zone,notes
```

Example row:

```
FGT-OT-PROD-01,port3,OT_LAN,NSS OT-All,Primary OT LAN segment
```

Column notes:
- `device` — exact device name as it appears in FortiManager
- `interface` — exact interface name as it appears on the device
- `alias` — short label used in policy naming (becomes the interface abbreviation in rule names)
- `policy_zone` — exact 4THealth zone name; leave blank if unknown
- `notes` — free-text; ignored by the tooling but preserved in the file

### 3. Hand-edit

Open `device_zone_map.yaml` directly and follow the structure in `device_zone_map.example.yaml`:

```yaml
devices:
  "FGT-DEVICE-NAME":
    "port3":
      alias: "OT_LAN"
      policy_zone: "NSS OT-All"
      notes: ""
    "port4":
      alias: "IT_TRANSIT"
      policy_zone: null
      notes: "not yet mapped"
```

Use this method when you are adding one or two interfaces and do not want to run an import script.

### 4. Export to CSV for a colleague to fill in

```bash
python scripts/import_zone_map.py --export-csv interfaces.csv
```

This writes the current state of `device_zone_map.yaml` as a CSV, including any entries where `policy_zone` is still null. Send the CSV to a colleague who knows the network topology; after they fill in the zone names, re-import:

```bash
python scripts/import_zone_map.py --from-csv interfaces.csv
```

## Finding the right 4THealth zone name

Zone names must match exactly. The canonical list is in `docs/zone-name-mapping.md`. To look up a specific IP:

```
/check-policy   — enter the IP; the zone field in the output is the exact name to use
```

Or call the MCP tool directly:

```
check_ip_traffic(src_ip="10.14.59.1", dst_ip="10.0.0.1", service="any")
```

The `src_zone` and `dst_zone` fields in the response are the exact strings to enter in `policy_zone`.

## When a mapping is missing

The analyze-request output will show something like:

```
WARNING: The following interfaces have no policy_zone mapping:
  FGT-OT-PROD-01 / port5
  FGT-OT-PROD-01 / port6
Add these to device_zone_map.yaml before proceeding.
```

To resolve:

1. Find the zone name for those interfaces using `check_ip_traffic` against a known IP in that subnet, or check the FortiManager GUI under the interface's zone assignment.
2. Add the entry to `device_zone_map.yaml` (hand-edit or re-run `--from-fortimanager` and fill in the null).
3. Re-run `/analyze-request`.

## NetBrain integration path

When NetBrain API access becomes available, `scripts/import_zone_map.py` will add a `--from-netbrain` mode. NetBrain has full topology data and can auto-resolve the `policy_zone` field for each interface without engineer input. Until then, the `--from-fortimanager` bootstrap gets the device/interface structure right and engineer knowledge fills in the zone names.

## Keeping the file current

- **New device added to FortiManager:** run `--from-fortimanager` to add the new device's interfaces with null placeholders, then fill them in.
- **Interface renamed or removed:** the old entry will remain in the file harmlessly; remove it manually if you want to keep the file tidy.
- **Zone names changed in 4THealth:** search the YAML for the old zone name and update. The `get_zones()` tool always returns the current canonical list.
- **The file does not exist:** `get_interface_map()` returns `zone_map_missing: true` on every interface and logs a startup warning. The workflow still runs but generates `.conf` files with `UNKNOWN_ZONE` placeholders.
