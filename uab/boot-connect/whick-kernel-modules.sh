#!/bin/sh
# USB Live modloop-lts → /lib/modules/$KVER (Ventoy/Live 공통)

whick_modules_kver() {
  _k="$(uname -r)"
  if [ -d "/lib/modules/$_k/kernel" ]; then
    echo "$_k"
    return 0
  fi
  if [ -d "/lib/modules/modules/$_k/kernel" ]; then
    mkdir -p "/lib/modules/$_k"
    mountpoint -q "/lib/modules/$_k" 2>/dev/null \
      || mount --bind "/lib/modules/modules/$_k" "/lib/modules/$_k" 2>/dev/null \
      || ln -sf "modules/$_k" "/lib/modules/$_k" 2>/dev/null
    if [ -d "/lib/modules/$_k/kernel" ]; then
      echo "$_k"
      return 0
    fi
  fi
  # USB Live modloop: /lib/modules/*-lts (uname -r 일치 전에도 탐색)
  for _d in /lib/modules/*/kernel /lib/modules/modules/*/kernel; do
    [ -d "$_d" ] || continue
    _k="${_d#/lib/modules/}"
    _k="${_k#/modules/}"
    _k="${_k%/kernel}"
    case "$_k" in firmware) continue ;; esac
    echo "$_k"
    return 0
  done
  return 1
}

whick_modules_ready() {
  whick_modules_kver >/dev/null 2>&1
}

whick_mount_modloop_file() {
  _ml="$1"
  [ -f "$_ml" ] || return 1
  mkdir -p /lib/modules /tmp/.whick-ml
  umount /tmp/.whick-ml 2>/dev/null || true
  if mount -t squashfs -o ro,loop "$_ml" /tmp/.whick-ml 2>/dev/null \
    || mount -o ro,loop "$_ml" /tmp/.whick-ml 2>/dev/null; then
    if [ -d /tmp/.whick-ml/modules ]; then
      umount /lib/modules 2>/dev/null || true
      mount --bind /tmp/.whick-ml/modules /lib/modules 2>/dev/null && return 0
    fi
    umount /lib/modules 2>/dev/null || true
    mount --bind /tmp/.whick-ml /lib/modules 2>/dev/null && return 0
  fi
  umount /lib/modules 2>/dev/null || true
  mount -o ro,loop "$_ml" /lib/modules 2>/dev/null
}

whick_ensure_modloop() {
  whick_modules_ready && return 0
  if [ -x /etc/init.d/modloop ]; then
    /etc/init.d/modloop start 2>/dev/null || true
    sleep 1
    whick_modules_ready && return 0
  fi
  for _ml in /boot/modloop-lts /boot/modloop-virt /lib/modloop-lts /modloop-lts; do
    whick_mount_modloop_file "$_ml" && whick_modules_kver >/dev/null 2>&1 && return 0
  done
  return 1
}

whick_modprobe_one() {
  _k="$1"
  _m="$2"
  _base="$3"
  _probe="$4"
  $_probe -k "$_k" "$_m" 2>/dev/null && return 0
  $_probe "$_m" 2>/dev/null && return 0
  _ko="$(find "$_base/kernel" -name "${_m}.ko" -o -name "${_m}.ko.xz" 2>/dev/null | head -1)"
  [ -n "$_ko" ] && insmod "$_ko" 2>/dev/null && return 0
  return 1
}

whick_usb_rescan() {
  command -v mdev >/dev/null 2>&1 && mdev -s 2>/dev/null || true
  if [ -w /sys/bus/usb/drivers_probe ]; then
    for _d in /sys/bus/usb/devices/*-*; do
      [ -f "$_d/idVendor" ] || continue
      echo "$_d" > /sys/bus/usb/drivers_probe 2>/dev/null || true
    done
  fi
}

whick_load_usb_host_modules() {
  _k="$1"
  _base="$2"
  _probe="$3"
  for _m in usbcore usb_common xhci_hcd xhci_pci ehci_hcd ehci_pci ohci_hcd ohci_pci uhci_hcd; do
    whick_modprobe_one "$_k" "$_m" "$_base" "$_probe" || true
  done
  whick_usb_rescan
}

# ASIX USB Gigabit (장치관리자: ASIX USB to Gigabit Ethernet Family) → ax88179_178a
whick_wait_usb_eth() {
  _i=0
  while [ "$_i" -lt 45 ]; do
    for _n in /sys/class/net/*; do
      _name="${_n##*/}"
      [ "$_name" = "lo" ] && continue
      [ -d "$_n/wireless" ] && continue
      echo "$_name"
      return 0
    done
    whick_usb_rescan
    sleep 1
    _i=$((_i + 1))
  done
  return 1
}

whick_mount_firmware() {
  _fw="/opt/whick-boot-connect/firmware"
  [ -d "$_fw" ] || return 1
  mkdir -p /lib/firmware
  if mountpoint -q /lib/firmware 2>/dev/null; then
    return 0
  fi
  mount -o bind,ro "$_fw" /lib/firmware 2>/dev/null \
    || cp -a "$_fw/." /lib/firmware/ 2>/dev/null || return 1
  return 0
}

whick_reload_nic() {
  _k="$(whick_modules_kver 2>/dev/null)" || return 1
  _probe="modprobe"
  if ! command -v modprobe >/dev/null 2>&1 \
    && [ -x /opt/whick-boot-connect/mini/sbin/modprobe ]; then
    _probe="/opt/whick-boot-connect/mini/sbin/modprobe"
  fi
  # RTL8125/8126 — mainline r8169 (needs rtl8125/8126 fw before bind)
  rmmod r8169 2>/dev/null || true
  whick_modprobe_one "$_k" r8169 "/lib/modules/$_k" "$_probe" || true
  mdev -s 2>/dev/null || true
}

whick_net_profile() {
  _p="/opt/whick-boot-connect/net-profile"
  if [ -f "$_p" ]; then
    tr -d '\r\n' <"$_p"
    return 0
  fi
  echo "full"
}

whick_load_disk_modules() {
  _k="$1"
  _base="$2"
  _probe="$3"
  for _m in ahci libata scsi_mod sd_mod nvme nvme_core; do
    whick_modprobe_one "$_k" "$_m" "$_base" "$_probe" || true
  done
}

whick_eth_has_carrier() {
  for _n in /sys/class/net/*; do
    [ -d "$_n/wireless" ] && continue
    [ "$(cat "$_n/carrier" 2>/dev/null)" = "1" ] && return 0
  done
  return 1
}

whick_load_wired_drivers_sequential() {
  _k="$1"
  _base="$2"
  _probe="$3"
  whick_load_usb_host_modules "$_k" "$_base" "$_probe"
  for _m in mii usbnet cdc_ether cdc_ncm cdc_eem smsc95xx smsc75xx \
    ax88179_178a asix r8152 r8153_ecm rtl8150 dm9601 mcs7830 lan78xx ch9200; do
    whick_modprobe_one "$_k" "$_m" "$_base" "$_probe" || true
    whick_usb_rescan
    whick_eth_has_carrier && return 0
  done
  whick_wait_usb_eth >/dev/null 2>&1 || true
  whick_eth_has_carrier && return 0
  for _m in e1000e e1000 igb igc ice i40e ixgbe ixgbevf bnxt_en \
    atlantic atl1c stmmac 8139too r8169 r8168 tg3 bnx2 bnx2x; do
    whick_modprobe_one "$_k" "$_m" "$_base" "$_probe" || true
    whick_eth_has_carrier && return 0
  done
  whick_reload_nic 2>/dev/null || true
  whick_usb_rescan
  for _n in /sys/class/net/*; do
    _name="${_n##*/}"
    [ "$_name" = "lo" ] && continue
    [ -d "$_n/wireless" ] && continue
    ip link set "$_name" up 2>/dev/null || true
  done
}

whick_load_net_modules() {
  _prof="$(whick_net_profile)"
  _k="$(whick_modules_kver 2>/dev/null)" || return 1
  _base="/lib/modules/$_k"
  _probe="modprobe"
  if ! command -v modprobe >/dev/null 2>&1 \
    && [ -x /opt/whick-boot-connect/mini/sbin/modprobe ]; then
    _probe="/opt/whick-boot-connect/mini/sbin/modprobe"
  fi
  if command -v depmod >/dev/null 2>&1; then
    depmod -a "$_k" 2>/dev/null || true
  fi
  whick_mount_firmware 2>/dev/null || true
  whick_load_disk_modules "$_k" "$_base" "$_probe"
  if [ "$_prof" != "wired" ]; then
    $_probe cfg80211 2>/dev/null || true
  fi
  if [ "$_prof" != "wireless" ]; then
    if [ "$_prof" = "wired" ]; then
      whick_load_wired_drivers_sequential "$_k" "$_base" "$_probe"
      return 0
    fi
    whick_load_usb_host_modules "$_k" "$_base" "$_probe"
    # USB·PCI 유선 (ASIX ax88179, Realtek USB r8152, Realtek PCIe r8169, Intel igc/igb …)
    for _m in mii usbnet cdc_ether cdc_ncm cdc_eem smsc95xx smsc75xx \
      ax88179_178a asix r8152 r8153_ecm rtl8150 dm9601 mcs7830 lan78xx ch9200; do
      whick_modprobe_one "$_k" "$_m" "$_base" "$_probe" || true
    done
    whick_usb_rescan
    whick_wait_usb_eth >/dev/null 2>&1 || true
    for _m in e1000e e1000 igb igc ice i40e ixgbe ixgbevf bnxt_en \
      atlantic atl1c stmmac 8139too r8169 r8168 tg3 bnx2 bnx2x; do
      whick_modprobe_one "$_k" "$_m" "$_base" "$_probe" || true
    done
    whick_reload_nic 2>/dev/null || true
    whick_usb_rescan
    for _n in /sys/class/net/*; do
      _name="${_n##*/}"
      [ "$_name" = "lo" ] && continue
      [ -d "$_n/wireless" ] && continue
      ip link set "$_name" up 2>/dev/null || true
    done
    if [ "$_prof" = "wired" ]; then
      return 0
    fi
  fi
  if [ "$_prof" = "wired" ]; then
    return 0
  fi
  # Wi-Fi AP / station
  for _m in mac80211 iwlwifi iwlmvm rtl8188eu rtl8xxxu brcmfmac ath10k_pci \
    mt76 mt7921e mt7921-common mt7921u mt7921s \
    mt7925e mt7925-common mt7925u \
    rtw88_core rtw88_pci rtw88_usb \
    rtw88_8821ce rtw88_8821cu rtw88_8822ce rtw88_8723de \
    rtw89_core rtw89_pci rtw89_8852b_common rtw89_8852be \
    rtw89_8852ae rtw89_8852ce; do
    whick_modprobe_one "$_k" "$_m" "$_base" "$_probe" || true
  done
  _i=0
  while [ "$_i" -lt 15 ]; do
    for _n in /sys/class/net/*; do
      [ -d "$_n/wireless" ] || continue
      echo "whick wifi: ${_n##*/}" >&2
      rfkill unblock all 2>/dev/null || true
      return 0
    done
    sleep 1
    _i=$((_i + 1))
  done
  rfkill unblock all 2>/dev/null || true
}
