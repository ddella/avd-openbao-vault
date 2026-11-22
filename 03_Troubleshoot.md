
```bash
ansible-inventory -i inventories/net-prod/inventory.yml --host dc1-spine1 | python3 -c 'import json,sys; v=json.load(sys.stdin); print("ntp_settings loaded:", "ntp_settings" in v); print("ntp credentials loaded:", "ntp" in v)'ansible-inventory -i inventories/net-prod/inventory.yml --host dc1-spine1 | python3 -c 'import json,sys; v=json.load(sys.stdin); print("ntp_settings loaded:", "ntp_settings" in v); print("ntp credentials loaded:", "ntp" in v)'
```

```bash
printf 'Configs with NTP authentication keys: '; grep -R -l 'ntp authentication-key' inventories/net-prod/intended/configs | wc -l; printf 'Configs with NTP trusted keys: '; grep -R -l 'ntp trusted-key' inventories/net-prod/intended/configs | wc -l
```

```bash
ansible-inventory -i inventories/net-prod/inventory.yml --host dc1-spine1 \
  | python3 -c 'import json,sys; v=json.load(sys.stdin); print("tags config loaded:", "eos_designs_custom_templates" in v)'
```
