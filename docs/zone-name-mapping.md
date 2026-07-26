# Zone Name Mapping

The full guide for managing zone mappings — including how to populate the file, import/export workflows, and the NetBrain integration path — is in **`docs/device-zone-map.md`**.

This file is a quick reference for engineers who need to look up a zone name while building rules or filling in `device_zone_map.yaml`.

## Quick reference: 4THealth policy zone names

These are the exact strings to use in `policy_zone` entries and in `/check-policy` output. Names must match exactly — including capitalisation and spaces.

| Policy Zone Name | Abbreviation | Used In |
|---|---|---|
| NSS CIP-H-All | CIPH | address groups, policy names |
| NSS CIP-H-ControlCenter | CIPH_CC | address groups, policy names |
| NSS CIP-H-EMS | CIPH_EMS | address groups, policy names |
| NSS CIP-H-Synchrophaser | CIPH_SYNC | address groups, policy names |
| NSS Gas-All | GAS | address groups, policy names |
| NSS Gas-FW nets | GAS_FW | address groups, policy names |
| NSS Gas-SCADA | GAS_SCADA | address groups, policy names |
| NSS OT-All | OT | address groups, policy names |
| NSS OT Mgmt | OT_MGMT | address groups, policy names |
| NSS OT Shared Services | OT_SS | address groups, policy names |
| NSS IT Corporate (non-user) | IT_CORP | address groups, policy names |
| NSS IT DMZ | IT_DMZ | address groups, policy names |
| NSS Corp Internal | CORP_INT | address groups, policy names |
| Users Networks | USERS | address groups, policy names |
| Internet | INET | address groups, policy names |
| Internet NAT | INET_NAT | address groups, policy names |
| Remote Access | RA | address groups, policy names |
| Point of Presence SASE | SASE | address groups, policy names |
| Public Cloud | CLOUD | address groups, policy names |
| OT Hosting | OT_HOST | address groups, policy names |
| Critical Infrastructure Protection | CIP | address groups, policy names |
| Nuclear | NUC | address groups, policy names |
| Transmission | TRANS | address groups, policy names |
| Financial System | FIN | address groups, policy names |
| Enterprise Management | ENT_MGMT | address groups, policy names |
| Advanced Distribution Management System | ADMS | address groups, policy names |
| Advanced Meter Infrastructure | AMI | address groups, policy names |
| Legacy Energy Management System | LEGACY_EMS | address groups, policy names |
| Dynamic Energy Management System | DEMS | address groups, policy names |
| Physical Access Controls | PAC | address groups, policy names |
| Misc-Unknown | MISC | address groups, policy names |
| IT Lab | IT_LAB | address groups, policy names |

Abbreviations come from `standards_mcp/naming.yaml` (`zone_abbrevs` section). They are used in address group names (`AG_HISTORIAN_OT`) and policy names (`CHG0012345_OT_LAN_TO_IT_001`).

## FortiManager interface names

FortiManager interface names (`port3`, `dmz1`, `wan2`) vary per device and have no inherent relationship to these zone names. To see what interfaces a specific FortiGate has:

```
get_interface_map(adom="<adom_name>", device="<device_name>")
```

The `policy_zone` field on each interface entry (added by `zone_map.py`) is the translation from device interface to the 4THealth zone name above.

To find the zone for a specific IP address:

```
check_ip_traffic(src_ip="<ip>", dst_ip="<any_ip>", service="any")
```

The `src_zone` field in the response is the zone that IP belongs to.
